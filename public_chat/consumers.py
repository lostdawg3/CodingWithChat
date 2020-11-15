from django.core.serializers.python import Serializer
from django.core.paginator import Paginator
from django.core.serializers import serialize
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
import json
from django.utils import timezone
from django.conf import settings

from public_chat.models import PublicChatRoom, PublicRoomChatMessage
from public_chat.constants import *
from chat.exceptions import ClientError
from chat.utils import calculate_timestamp

# fron django.contrib.auth import get_user_model is the same thing as from django.contrib import settings then ... user = settings.AUTH_USER_MODEL



class PublicChatConsumer(AsyncJsonWebsocketConsumer):

	async def connect(self):
		"""
		Called when the websocket is handshaking as a part of inital connection
		the self.scope is similar to request.user in the view
		self.scope['user']
		"""
		print("PublicChatConsumer: connect: " + str(self.scope['user']))
		await self.accept()

		self.room_id = None


		# # Add them to the group so they can get room messages
		# await self. channel_layer.group_add(
		# 	"public_chatroom_1",		# hardcoded for now
		# 	self.channel_name
		# )

	async def disconnect(self, code):
		""""
		Called when the websocket closes for any reason.
		"""
		print("PublicChatConsumer: disconnect")
		try:
	 		if self.room_id != None:
	 			await self.leave_room(self.room_id)
		except Exception as e:
			pass

	async def receive_json(self, content):
		"""
		Called when we get a text frame. Channles will JSON-decode the payload fro us and pass it as the first argument.
		"""
		command = content.get("command", None)
		# message = content.get("message", None)	# can use this to see what message is 
		print("PublicChatConsumer: receive_json: " + str(command))
		# print("PublicChatConsumer: receive_json: " + str(message))
		# in order to get the send from command you can either use 
		# content.get("command", None) or you can use content['message']
		try:
			if command == "send":
				if len(content['message'].lstrip()) == 0:
					# raise Exception("nothing here")
					raise ClientError(422, "you can't send an empty message")
					# MDN web docs 422 Unproccessable entity
				# await self.send_json({
				# 	"message": content['message']
				# })
				# await self.send_message(content['room_id'], content['message'])

				# now using send_room instead of send_message.
				await self.send_room(content['room_id'], content['message'])
			elif command == "join":
				# mitch uses room inside of the addeventlistener (home.html)
				await self.join_room(content['room_id']) 
			elif command == "leave":
				# same as above
				await self.leave_room(content['room_id']) 
			elif command == "get_room_chat_messages":
				await self.display_progress_bar(True)
				room = await get_room_or_error(content['room_id'])
				payload = await get_room_chat_messages(room, content['page_number'])
				if payload != None:
					payload = json.loads(payload)
					await self.send_messages_payload(payload['messages'], payload['new_page_number'])
				else: 
					raise ClientError(204, "Something went wrong retrieving chatroom messages.")
				await self.display_progress_bar(False)
		except ClientError as e:
			await self.display_progress_bar(False)
			await self.handle_client_error(e)
			

	async def send_room(self, room_id, message):
		"""
		Called by receive_json when someone sends a message to a room
		"""
		print("PublicChatConsumer: send_room")

		if self.room_id != None:
			if str(room_id) != str(self.room_id):
				raise ClientError("ROOM_ACCESS_DENIED", "Room access denied")
			if not is_authenticated(self.scope['user']):
				raise ClientError("AUTH_ERROR", "You must be authenticated to chat.")
		else: 
			raise ClientError("ROOM_ACCESS_DENIED", "Room access denied.")

		room = await get_room_or_error(room_id)
		await create_public_room_chat_message(room, self.scope['user'], message)

		await self.channel_layer.group_send(
		room.group_name,		
		{
			"type": "chat.message",		
			"profile_image": self.scope['user'].profile_image.url,
			"username": self.scope['user'].username,
			"user_id": self.scope['user'].id,
			"message": message,
		}
	)

	# async def send_message(self, message):
	# 	await self.channel_layer.group_send(
	# 		"public_chatroom_1",		# hardcoded, will change later
	# 		{
	# 			"type": "chat.message",		#chat_message (ex. "chat.message.now == chat_message_now". Will call the chat_message function below and pass all of these parameters inside the event argument)
	# 			"profile_image": self.scope['user'].profile_image.url,
	# 			"username": self.scope['user'].username,
	# 			"user_id": self.scope['user'].id,
	# 			"message": message,
	# 		}
	# 	)

	async def chat_message(self, event):
		"""
		Called when someone has messaged our chat
		"""

		# Send a message down to the client
		print("PublicChatConsumer: chat_message from user #: " + str(event['user_id']))
		timestamp = calculate_timestamp(timezone.now())
		# timestamp = calculate_timestamp(timezone.localtime(timezone.now()))
		# print("timezone is " + str(timezone.now))
		await self.send_json({
			"msg_type": MSG_TYPE_MESSAGE,
			"profile_image": event['profile_image'],
			"username": event['username'],
			"user_id": event['user_id'],
			"message": event['message'],
			"natural_timestamp": timestamp,
		})

	async def join_room(self, room_id):
		"""
		Called by receive_json when someone sent a JOIN command
		"""
		print("PublicChatConsumer: join_room")

		is_auth = is_authenticated(self.scope['user'])

		try:
			room = await get_room_or_error(room_id)
		except ClientError as e:
			await self.handle_client_error(e)	

		# Add user to "users" list for room
		if is_auth:
			await connect_user(room, self.scope['user'])

		# Store that we're in the room
		self.room_id = room.id

		# Add them to the group so they get the room messages
		await self.channel_layer.group_add(
			room.group_name,
			self.channel_name
		)

		# Tell the client to finish opening the room
		await self.send_json({
			"join": str(room.id),
			"username": self.scope['user'].username,
		})

		num_connected_users = get_num_connected_users(room)
		await self.channel_layer.group_send(
			room.group_name,
			{
				"type": "connected.user.count",
				"connected_user_count": num_connected_users
			}
		)

	async def leave_room(self, room_id):
		"""
		Called by receive_json when someone sent a LEAVE command
		"""
		print("PublicChatConsumer: leave_room")

		is_auth = is_authenticated(self.scope['user'])

		try:
			room = await get_room_or_error(room_id)
		except ClientError as e:
			await self.handle_client_error(e)	


		# Remove user from 'users' list
		if is_auth:
			await disconnect_user(room, self.scope['user'])

		# Remove that we're in the room
		self.room_id = None

		# Remove themn from the group so they no longer receive messages
		await self.channel_layer.group_discard(
			room.group_name,
			self.channel_name
		)

		num_connected_users = get_num_connected_users(room)
		await self.channel_layer.group_send(
			room.group_name,
			{
				"type": "connected.user.count",
				"connected_user_count": num_connected_users
			}
		)

	async def send_messages_payload(self, messages, new_page_number):
		"""
		Sends a payload of messages to the UI
		"""
		print("PublicChatConsumer: send_messages_payload.")
		await self.send_json({
			"messages_payload": "messages_payload",
			"messages": messages,
			"new_page_number": new_page_number,	
		})

	async def handle_client_error(self, e):
		"""
		Called when a client error is raised.
		Sends error data to the UI
		"""
		errorData = {}
		errorData['error'] = e.code
		if e.message:
			errorData['message'] = e.message
			await self.send_json(errorData)
		return

	async def display_progress_bar(self, is_displayed):
		"""
		1. is_displayed = True
			- Display the progres bar on UI
		2. is_displayed = False
			- hide the progress bar on UI
		"""
		print("DISPLAY PROGRESS BAR: " + str(is_displayed))
		await self.send_json({
			"display_progress_bar": is_displayed	
		})

	async def connected_user_count(self, event):
		"""
		Called to send the number of connected users to the room.
		This number is displayed in the romm so other users know how many users are connected to the chat.
		"""
		print("PublicChatConsumer: connected_user_count: " + str(event['connected_user_count']))
		await self.send_json({
			"msg_type": MSG_TYPE_CONNECTED_USER_COUNT,
			"connected_user_count": event['connected_user_count']
		})


def get_num_connected_users(room):
	if room.users:
		return len(room.users.all())
	return 0




def is_authenticated(user):
	if user.is_authenticated:
		return True
	return False

@database_sync_to_async
def create_public_room_chat_message(room, user, message):
	return PublicRoomChatMessage.objects.create(user=user, room=room, content=message)

@database_sync_to_async
def connect_user(room, user):
	return room.connect_user(user)

@database_sync_to_async
def disconnect_user(room, user):
	return room.disconnect_user(user)

@database_sync_to_async
def get_room_or_error(room_id):
	"""
	Tries to fetch a room for the user
	"""
	try:
		room = PublicChatRoom.objects.get(pk=room_id)
	except PublicChatRoom.DoesNotExist:
		raise ClientError("ROOM_INVALID", "Invalid room")
	return room


@database_sync_to_async
def get_room_chat_messages(room, page_number):
	try:
		qs = PublicRoomChatMessage.objects.by_room(room)
		p = Paginator(qs, DEFAULT_ROOM_CHAT_MESSAGE_PAGE_SIZE)
		payload = {}
		new_page_number = int(page_number)
		if new_page_number <= p.num_pages:
			new_page_number = new_page_number + 1
			s = LazyRoomChatMessageEncoder()
			payload['messages'] = s.serialize(p.page(page_number).object_list)
		else: 
			payload['messages'] = "None"
		payload['new_page_number'] = new_page_number
		return json.dumps(payload)
	except Exception as e:
		print("EXCEPTION: " + str(e))
		return None

class LazyRoomChatMessageEncoder(Serializer):
	def get_dump_object(self, obj):
		dump_object = {}
		dump_object.update({'msg_type': MSG_TYPE_MESSAGE})
		dump_object.update({'user_id': str(obj.user.id)})
		dump_object.update({'msg_id': str(obj.id)})
		dump_object.update({'username': str(obj.user.username)})
		dump_object.update({'message': str(obj.content)})
		dump_object.update({'profile_image': str(obj.user.profile_image.url)})
		dump_object.update({'natural_timestamp': calculate_timestamp(obj.timestamp)})
		return dump_object





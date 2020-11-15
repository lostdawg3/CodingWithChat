from django.contrib import admin

from notification.models import Notification


class NotificationAdmin(admin.ModelAdmin):

	list_filter = ['content_type']
	list_display = ['target', 'content_type', 'timestamp']
	search_fields = ['target_username', 'target_email']
	readonly_fields = []

	class Meta:
		model = Notification 


admin.site.register(Notification, NotificationAdmin)






from datetime import datetime, timedelta
from smtplib import SMTPException

from celery.decorators import periodic_task
from django.core.mail import send_mail
from task_manager.celery import app

from tasks.models import STATUS_CHOICES, Task, UserPreferences


@app.task
def process_email(user):
    email_content = f"Hello {user.username}!\n\n"
    email_content += "Here is your tasks summary:\n"
    all_tasks = Task.objects.filter(user=user, deleted=False)
    for status in STATUS_CHOICES:
        tasks = all_tasks.filter(status=status[0])
        if tasks.exists():
            email_content += f"\n{len(tasks)} {status[1].lower()} task(s).\n"
    email_content += "\n\n"
    email_content += "Thank you!"
    try:
        send_mail("Tasks summary", email_content, "tasks@task_manager.org", [user.email], fail_silently=False,)
        user.last_sent = datetime.now()
        user.save()
    except SMTPException as e:
        print("Error sending email", e)


@periodic_task(run_every=timedelta(seconds=30))
def send_reports():
    new_and_missing_users = UserPreferences.objects.filter(reminder_enabled=True, last_sent__lte=datetime.now() - timedelta(hours=24))
    if len(new_and_missing_users) == 0:
        print("No matching users found")
    for user_prefs in new_and_missing_users:
        print("Processing", user_prefs.user)
        process_email.delay(user_prefs.user)

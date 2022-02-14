from datetime import datetime, timedelta
from smtplib import SMTPException

from celery.decorators import periodic_task
from django.core.mail import send_mail

from tasks.models import STATUS_CHOICES, Task, UserPreferences
from django.db.models import Q
from django.utils.timezone import make_aware


def get_email_content(user):
    all_tasks = Task.objects.filter(user=user, deleted=False)
    email_content = f"Hello {user.username}!\n\n"
    email_content += "Here is your tasks summary:\n"
    for status in STATUS_CHOICES:
        tasks = all_tasks.filter(status=status[0])
        if tasks.exists():
            email_content += f"\n{tasks.count()} {status[1].lower()} task(s).\n"
    email_content += "\n\n"
    email_content += "Thank you!"

    return email_content


@periodic_task(run_every=timedelta(seconds=30))
def send_reports():
    current_time = make_aware(datetime.now())
    reminder_enabled = Q(reminder_enabled=True)
    missed_last_reminder = Q(last_sent__lte=make_aware(datetime.now() - timedelta(hours=24)))
    reminder_fail = Q(last_sent=None) & Q(reminder_time__lte=current_time)
    reminder_in_last_30_secs = Q(reminder_time__range=(current_time - timedelta(seconds=30), current_time))

    new_and_missing_users = UserPreferences.objects.filter((reminder_enabled) & (missed_last_reminder | reminder_fail | reminder_in_last_30_secs))

    for user_prefs in new_and_missing_users:
        print("Processing", user_prefs.user)
        try:
            email_content = get_email_content(user_prefs.user)
            send_mail("Tasks summary", email_content, "tasks@task_manager.org", [user_prefs.user.email], fail_silently=False,)
            user_prefs.last_sent = make_aware(datetime.now())
            user_prefs.save()
        except SMTPException as e:
            print("Error sending email", e)

from datetime import datetime, timedelta

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db import transaction
from django.forms import ModelForm
from django.http import HttpResponseRedirect
from django.utils.timezone import make_aware
from django.views.generic.edit import CreateView, DeleteView, UpdateView
from django.views.generic.list import ListView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

from tasks.filters import TaskFilter, TaskStatusChangeFilter
from tasks.models import Task, TaskStatusChange, UserPreferences
from tasks.serializer import TaskSerializer, TaskStatusChangeSerializer


class AuthorisationCheck(LoginRequiredMixin):
    def get_queryset(self):
        return Task.objects.filter(deleted=False, user=self.request.user)


class UserLoginView(LoginView):
    template_name = "login.html"
    redirect_authenticated_user = True
    success_url = "/tasks"


class UserLogoutView(LoginRequiredMixin, LogoutView):
    redirect_authenticated_user = True
    success_url = "/user/logout"


class UserCreateView(CreateView):
    form_class = UserCreationForm
    template_name = "signup.html"
    success_url = "/user/login"


class TaskView(LoginRequiredMixin, ListView):
    template_name = "tasks.html"
    context_object_name = "tasks"

    def get_context_data(self, **kwargs):
        tasks = Task.objects.filter(deleted=False, user=self.request.user)
        context_data = super().get_context_data(**kwargs)
        context_data["completed_tasks"] = tasks.filter(completed=True).count()
        context_data["total_tasks"] = tasks.count()
        return context_data

    def get_queryset(self):
        tasks = Task.objects.filter(deleted=False, user=self.request.user)
        filter_term = self.request.GET.get("filter")
        if filter_term:
            tasks = tasks.filter(completed=(filter_term == "completed"))
        return tasks.order_by("priority")


def update_priorities(self, form):
    current_priority = form.instance.priority
    all_tasks = (
        Task.objects.filter(
            priority__gte=current_priority,
            deleted=False,
            completed=False,
            user=form.instance.user,
        )
        .exclude(pk=form.instance.id)
        .select_for_update()
        .order_by("priority")
    )

    with transaction.atomic():
        queries = []
        for task in all_tasks:
            if task.priority > current_priority:
                break
            current_priority = task.priority = task.priority + 1
            queries.append(task)
        if queries:
            Task.objects.bulk_update(queries, ["priority"], batch_size=100)
        self.object = form.save()


class TaskCreateForm(ModelForm):
    class Meta:
        model = Task
        fields = ["title", "description", "priority", "completed"]


class PreferencesForm(ModelForm):
    class Meta:
        model = UserPreferences
        fields = ["reminder_enabled", "reminder_time"]


class TaskCreateView(LoginRequiredMixin, CreateView):
    form_class = TaskCreateForm
    template_name = "task_create.html"
    success_url = "/tasks"

    def form_valid(self, form):
        form.instance.user = self.request.user
        update_priorities(self, form)
        return super().form_valid(form)


class UpdateTaskView(AuthorisationCheck, UpdateView):
    model = Task
    form_class = TaskCreateForm
    template_name = "task_edit.html"
    success_url = "/tasks"

    def get_queryset(self):
        return Task.objects.filter(deleted=False, user=self.request.user)

    def form_valid(self, form):
        update_priorities(self, form)
        return super().form_valid(form)


class DeleteTaskView(AuthorisationCheck, DeleteView):
    success_url = "/tasks"
    model = Task
    template_name = "task_delete.html"

    def get_queryset(self):
        return Task.objects.filter(deleted=False, user=self.request.user)


def toggle_complete_task(request, pk):
    if not request.user.is_authenticated:
        return HttpResponseRedirect("/user/login")
    task = Task.objects.filter(id=pk, deleted=False, user=request.user)
    if task.exists():
        task.update(completed=not task[0].completed)
    return HttpResponseRedirect("/tasks")


def index_page(request):
    return HttpResponseRedirect("/tasks")


class TaskStatusChangeViewAPI(ReadOnlyModelViewSet):
    queryset = TaskStatusChange.objects.all()
    serializer_class = TaskStatusChangeSerializer

    permission_classes = (IsAuthenticated,)

    filter_backends = (DjangoFilterBackend,)
    filterset_class = TaskStatusChangeFilter

    def get_queryset(self):
        return TaskStatusChange.objects.filter(task__user=self.request.user, task__deleted=False)


class TaskStatusChangeViewNestedAPI(ReadOnlyModelViewSet):
    queryset = TaskStatusChange.objects.all()
    serializer_class = TaskStatusChangeSerializer

    permission_classes = (IsAuthenticated,)

    filter_backends = (DjangoFilterBackend,)
    filterset_class = TaskStatusChangeFilter

    def get_queryset(self):
        return TaskStatusChange.objects.filter(
            task=self.kwargs["task_pk"], task__user=self.request.user, task__deleted=False
        )


class TaskViewSetAPI(ModelViewSet):
    queryset = Task.objects.all()
    serializer_class = TaskSerializer

    permission_classes = (IsAuthenticated,)

    filter_backends = (DjangoFilterBackend,)
    filterset_class = TaskFilter

    def get_queryset(self):
        return Task.objects.filter(user=self.request.user, deleted=False)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        if serializer.validated_data.get("status") and serializer.instance.status != serializer.validated_data.get(
            "status"
        ):
            TaskStatusChange.objects.create(
                task=serializer.instance,
                original_status=serializer.instance.status,
                updated_status=serializer.validated_data.get("status"),
                user=self.request.user,
            )

        serializer.save(user=self.request.user)


class PreferencesView(LoginRequiredMixin, UpdateView):
    form_class = PreferencesForm
    template_name = "preferences.html"
    success_url = "/tasks"

    def get_object(self):
        tasks = UserPreferences.objects.get_or_create(user=self.request.user)[0]
        return tasks

    def form_valid(self, form):
        pref = UserPreferences.objects.get(user=self.request.user)
        if form.instance.reminder_enabled:
            current_time = datetime.now()
            if not pref.last_sent or pref.last_sent <= make_aware(current_time - timedelta(days=1)):
                pref.last_sent = make_aware(datetime.combine(current_time, form.instance.reminder_time) - timedelta(days=1))
            else:
                pref.last_sent = make_aware(datetime.combine(current_time, form.instance.reminder_time))
            pref.save()
        return super().form_valid(form)

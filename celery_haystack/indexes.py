from django.db.models import signals

from haystack import constants, indexes
from haystack.utils import get_identifier

from celery_haystack.utils import get_update_task

from appconf import AppConf


class CeleryHaystack(AppConf):
    DEFAULT_ALIAS = None
    RETRY_DELAY = 5 * 60
    MAX_RETRIES = 1
    DEFAULT_TASK = 'celery_haystack.tasks.CeleryHaystackSignalHandler'

    COMMAND_BATCH_SIZE = None
    COMMAND_AGE = None
    COMMAND_REMOVE = False
    COMMAND_WORKERS = 0
    COMMAND_APPS = []
    COMMAND_VERBOSITY = 1

    def configure_default_alias(self, value):
        return value or getattr(constants, 'DEFAULT_ALIAS', None)

    def configure(self, value):
        data = {}
        for name, value in self.configured_data.items():
            if name in ('RETRY_DELAY', 'MAX_RETRIES',
                        'COMMAND_WORKERS', 'COMMAND_VERBOSITY'):
                value = int(value)
            data[name] = value
        return data


class CelerySearchIndex(indexes.SearchIndex):
    """
    A ``SearchIndex`` subclass that enqueues updates/deletes for later
    processing using Celery.
    """
    def __init__(self, *args, **kwargs):
        super(CelerySearchIndex, self).__init__(*args, **kwargs)
        self.task_cls = get_update_task()
        self.has_get_model = hasattr(self, 'get_model')

    def handle_model(self, model):
        if model is None and self.has_get_model:
            return self.get_model()
        return model

    # We override the built-in _setup_* methods to connect the enqueuing
    # operation.
    def _setup_save(self, model=None):
        model = self.handle_model(model)
        signals.post_save.connect(self.enqueue_save, sender=model)

    def _setup_delete(self, model=None):
        model = self.handle_model(model)
        signals.post_delete.connect(self.enqueue_delete, sender=model)

    def _teardown_save(self, model=None):
        model = self.handle_model(model)
        signals.post_save.disconnect(self.enqueue_save, sender=model)

    def _teardown_delete(self, model=None):
        model = self.handle_model(model)
        signals.post_delete.disconnect(self.enqueue_delete, sender=model)

    def enqueue_save(self, instance, **kwargs):
        return self.enqueue('update', instance)

    def enqueue_delete(self, instance, **kwargs):
        return self.enqueue('delete', instance)

    def enqueue(self, action, instance):
        """
        Shoves a message about how to update the index into the queue.

        This is a standardized string, resembling something like::

            ``notes.note.23``
            # ...or...
            ``weblog.entry.8``
        """
        return self.task_cls.delay(action, get_identifier(instance))

'''JSON logging module for Python logging'''
import datetime as dt
import json
import logging

EXTRA_KEYS = [
    "aws_profile",
    "aws_access_key_id",
    "use_env_vars",
    "use_instance_profile",
    "aws_secret_access_key",
    "aws_session_token",
    "aws_region_name",
    "target_url",
    "api_gateway_id",
    "command"
]


class JSONFormatter(logging.Formatter):
    '''Formatter for standard Python logging output to convert to JSON.
    Handles exception metadata via object __dict__ and can be extended using EXTRA_KEYS.

    Methods:
        format: Push record through log preparation. Then convert dictionary to JSON and return.
        _prepare_log_dict: Guarantee specific values, process exception data, and allow extension.
    '''
    def __init__(self, *, fmt_keys: dict[str, str] | None = None):
        super().__init__()
        self.fmt_keys = fmt_keys if fmt_keys is not None else {}


    def format(self, record: logging.LogRecord) -> str:
        message = self._prepare_log_dict(record)
        return json.dumps(message, default=str)


    def _prepare_log_dict(self, record: logging.LogRecord):
        always_fields = {
            "message": record.getMessage(),
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.timezone.utc).isoformat()
        }

        if record.exc_info is not None:
            always_fields["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info is not None:
            always_fields["stack_info"] = self.formatStack(record.stack_info)

        message = {
            key: msg_val
            if (msg_val := always_fields.pop(val, None)) is not None
            else getattr(record, val)
            for key, val in self.fmt_keys.items()
        }

        message.update(always_fields)

        for key, val in record.__dict__.items():
            if key in EXTRA_KEYS:
                message[key] = val

        return message

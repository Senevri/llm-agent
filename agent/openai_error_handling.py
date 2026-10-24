import openai
import logging
import time

logger = logging.getLogger(__name__)
from enum import Enum

class Action(Enum):
    ABORT = "abort"
    RETRY = "retry"
    BACKOFF = "backoff"

_FATAL = (openai.BadRequestError, openai.AuthenticationError,
          openai.NotFoundError, openai.PermissionDeniedError)

def classify_api_error(e: Exception) -> tuple[Action, float]:
    if isinstance(e, _FATAL):
        body = getattr(e, "body", None)
        if isinstance(body, dict) and body.get("type"):
            logger.error(f"Fatal API error: type={body['type']} code={body.get('code')}")
        return Action.ABORT, 0.0
    if isinstance(e, openai.RateLimitError):
        return Action.BACKOFF, 10.0
    if isinstance(e, (openai.APIConnectionError, openai.InternalServerError)):
        return Action.RETRY, 5.0
    if isinstance(e, openai.APIError):
        return Action.RETRY, 5.0
    return Action.ABORT, 0.0
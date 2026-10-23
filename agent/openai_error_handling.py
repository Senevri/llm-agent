import openai
import logging
import time

logger = logging.getLogger(__name__)

def handle_api_error(e: Exception):
    if e in (openai.BadRequestError, openai.AuthenticationError, openai.NotFoundError, openai.PermissionDeniedError):
        # permanent config errors — retrying will never help
        logger.error(f"Fatal API error (will not retry): {e}")
        body = getattr(e, "body", None)
        if isinstance(body, dict) and body.get("type"):
            logger.error(f"  type={body['type']} code={body.get('code')}")
        raise SystemExit(1)
    elif e in (openai.RateLimitError):
        logger.warning(f"Rate limited, backing off: {e}")
        time.sleep(10)
        return
    elif e in (openai.APIConnectionError, openai.InternalServerError):
        logger.error(f"Transient API error, retrying: {e}")
        time.sleep(5)
        return
    elif isinstance(e, openai.APIError):
        logger.error(f"Unclassified API error: {e}")
        return
    else:
        logger.error(f"Unexpected error: {e}")
        raise SystemExit(1)

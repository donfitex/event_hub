from rest_framework.renderers import JSONRenderer


def _is_enveloped(data):
    return isinstance(data, dict) and "data" in data and set(data) <= {"data", "meta"}


class EnvelopeJSONRenderer(JSONRenderer):
    """Wrap successful responses as {"data": ...}. Errors are shaped by the exception handler."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        if (
            response is not None
            and response.status_code < 400
            and data is not None
            and not _is_enveloped(data)
        ):
            data = {"data": data}
        return super().render(data, accepted_media_type, renderer_context)
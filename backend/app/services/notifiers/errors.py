class DeliveryError(Exception):
    """A notification couldn't be delivered. Worth retrying (network, 5xx, SMTP down)."""

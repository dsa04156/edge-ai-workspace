"""Profile-driven Virtual Device Runtime prototype."""

from .config import DeviceProfile, ProfileValidationError, load_profile

__all__ = [
    "DeviceProfile",
    "ProfileValidationError",
    "load_profile",
]

__version__ = "0.1.0"

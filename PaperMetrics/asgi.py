"""
ASGI config for PaperMetrics project.

This module configures your Django application to run with an Asynchronous Server Gateway Interface (ASGI),
which is the standard for handling asynchronous requests in Python.

It exposes the ASGI callable as a module-level variable named `application`.

For more information on this file, see:
https://docs.djangoproject.com/en/3.0/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

# Set the default Django settings module for the 'asgi' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'PaperMetrics.settings')

# This application object is used by any ASGI server configured to use this file.
application = get_asgi_application()

# If you are planning to use channels or any other advanced ASGI features,
# you might need to configure additional elements here. For example, if you were
# to integrate Django Channels for WebSocket handling, you would extend the application
# setup like so:

# from channels.auth import AuthMiddlewareStack
# from channels.routing import ProtocolTypeRouter, URLRouter
# import myapp.routing

# application = ProtocolTypeRouter({
#     "http": get_asgi_application(),
#     "websocket": AuthMiddlewareStack(
#         URLRouter(
#             myapp.routing.websocket_urlpatterns
#         )
#     ),
# })

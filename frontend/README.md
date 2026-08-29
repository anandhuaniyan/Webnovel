# Webnovel frontend

The frontend is a dependency-free static site served by its dedicated Nginx container. All assets are local to this directory; it loads no third-party scripts, fonts, images, or trackers.

Compose publishes the site on the project-specific `WEBNOVEL_FRONTEND_PORT` recorded in the root `.env` file.

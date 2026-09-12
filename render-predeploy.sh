#!/bin/sh
# Pre-deploy script for Render — kept as a real file rather than an inline
# "&&"-chained command in the dashboard's Pre-Deploy Command field, since
# that field (like Fly's release_command and Railway's preDeployCommand
# before it) doesn't reliably parse shell operators typed directly into it.
set -e
python manage.py migrate --noinput
python manage.py createcachetable

@echo off
REM 启动 Celery Worker

echo Starting Celery Worker...
celery -A src.celery_app worker --loglevel=info --pool=solo

pause

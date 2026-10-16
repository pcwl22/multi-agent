FROM python:3.13-slim
RUN pip install --no-cache-dir fastapi==0.136.3 httpx==0.28.1 pytest==8.3.4
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
USER 65534:65534
WORKDIR /workspace
CMD ["python", "-m", "pytest", "tests", "-q"]

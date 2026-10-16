FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY frontend ./frontend
COPY demo_repository ./demo_repository
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", "8000"]

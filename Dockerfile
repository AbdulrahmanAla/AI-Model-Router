FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -c requirements.lock -r requirements.txt
COPY app ./app
COPY web ./web
RUN useradd --create-home assistant
USER assistant
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

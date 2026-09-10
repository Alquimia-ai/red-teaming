FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "boto3>=1.35"
COPY main.py .
EXPOSE 8080
CMD ["python", "main.py"]

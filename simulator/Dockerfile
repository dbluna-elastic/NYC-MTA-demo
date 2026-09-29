FROM python:3.12-slim
WORKDIR /app
COPY simulator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simulator/simulator.py .
COPY simulator/scenarios ./scenarios
ENV PYTHONUNBUFFERED=1
CMD ["python", "simulator.py", "--once"]

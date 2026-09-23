FROM python:3.12-slim
RUN pip install --no-cache-dir aiohttp cryptography
COPY qkd_sim.py /app/qkd_sim.py
EXPOSE 8080
CMD ["python", "/app/qkd_sim.py"]
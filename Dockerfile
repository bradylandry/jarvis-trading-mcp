FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY friend_mcp/ ./friend_mcp/
ENV HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["python", "-m", "friend_mcp.server"]

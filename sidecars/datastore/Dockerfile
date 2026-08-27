FROM alpine:3.20

# Install dependencies
RUN apk update && apk add --no-cache python3 py3-pip s3fs-fuse

# Create the base directory for S3 data
RUN mkdir -p /s3-data

# Copy the scripts
COPY entrypoint.sh /entrypoint.sh
COPY app.py /app/app.py
COPY requirements.txt .
COPY mount.py /app/mount.py

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencys
RUN pip install -r requirements.txt

# Make entrypoint executable
RUN chmod +x /entrypoint.sh

# Set working directory
WORKDIR /app

# Set the entrypoint
ENTRYPOINT ["/entrypoint.sh"]

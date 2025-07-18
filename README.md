# Trendwatch

This repo packages the Trendwatch YouTube Shorts pipeline and a small MCP server for Cloud Run.

## Local Development

```bash
pip install -r requirements.txt
python -m app.pipeline --help
```

To serve the MCP endpoint locally:

```bash
DATA_PATH=trendwatch.parquet python -m app.server
```

Build the Docker image for deployment:

```bash
docker build -t trendwatch .
```

# A static page, served. No backend: the panel is a WebSocket client of the
# same socket the browser client uses (panel/README.md).
FROM python:3.12-alpine
WORKDIR /srv
COPY index.html spans.js ./
EXPOSE 3100
CMD ["python3", "-m", "http.server", "3100", "--directory", "/srv"]

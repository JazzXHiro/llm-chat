# Windows: install make with  winget install ezwinports.make

.PHONY: up down logs reset

# Build both images and start them; returns once the backend is healthy
up:
	docker compose up --build -d --wait
	@echo Frontend: http://localhost:3000
	@echo Backend:  http://localhost:8000/health

# Stop and remove the containers (the chat-data volume is kept)
down:
	docker compose down

# Follow the logs of both services (Ctrl+C to stop)
logs:
	docker compose logs -f

# Stop everything AND delete the SQLite volume (all chat history)
reset:
	docker compose down -v

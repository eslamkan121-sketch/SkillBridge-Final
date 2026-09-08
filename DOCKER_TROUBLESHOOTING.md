# Docker Troubleshooting Guide

## Issue: "Port 8000 already in use"

**Symptom**: `docker compose up` fails with "Address already in use"

**Solution**:
```bash
# Option 1: Kill the process on port 8000
lsof -ti:8000 | xargs kill -9        # macOS/Linux
netstat -ano | findstr :8000         # Windows (find PID, then: taskkill /PID xxx /F)

# Option 2: Use a different port (set in .env)
echo "BACKEND_PORT=8001" >> .env
docker compose up -d
```

---

## Issue: "Backend container exits with code 3"

**Symptom**: `docker compose ps` shows backend `Exited (3)`

**Solution**: Check logs for the real error
```bash
docker compose logs backend | tail -50
```

Common causes:
- Database file permissions: `docker compose exec backend ls -la /app/data/`
- Missing dependencies: `docker compose build --no-cache backend && docker compose up -d`
- Python import error: Check `/app/app/main.py` syntax

---

## Issue: "Frontend can't connect to backend (CORS error)"

**Symptom**: Browser console shows CORS error, frontend won't load data

**Causes**:
1. Backend not running: `docker compose ps` → check backend status
2. Wrong API URL: Check `VITE_API_URL` env var (should be `http://localhost:8000`)
3. Backend health check failing: `docker logs skillbridge-backend`

**Solution**:
```bash
# Verify backend is healthy
docker compose ps

# Restart both services
docker compose restart backend frontend

# Check frontend is using correct API URL
docker compose exec frontend env | grep VITE
```

---

## Issue: "Database connection refused"

**Symptom**: Backend logs show "unable to open database file" or PostgreSQL connection error

**Solution**:
```bash
# Check DB is running
docker compose ps db

# Verify DB health
docker compose exec db pg_isready

# Check database file exists
docker compose exec backend ls -la /app/data/

# If data directory doesn't exist, rebuild
docker compose down -v
docker compose up -d
```

---

## Issue: "Health check failing (unhealthy)"

**Symptom**: `docker compose ps` shows `(unhealthy)` status

**Solution**:
```bash
# View health check details
docker inspect skillbridge-backend --format '{{json .State.Health}}' | jq .

# Backend health check: tries to reach /api/universities
# If failing, backend likely crashed. Check logs:
docker compose logs backend

# Common fix: restart services
docker compose restart
```

---

## Issue: "Volume mount not working (code changes don't reflect)"

**Symptom**: Change a file, but container doesn't see the change

**Causes**:
1. Wrong mount path in `docker-compose.yml`
2. Container caching: `/app/__pycache__` is explicitly excluded
3. File not saved: Check your editor

**Solution**:
```bash
# Verify volumes are mounted correctly
docker inspect skillbridge-backend | grep -A 20 Mounts

# Manually verify mount path
docker compose exec backend cat /app/app/main.py | head -5

# If still broken, rebuild without cache
docker compose down -v
docker compose up -d --build
```

---

## Issue: "Image build fails (pip install timeout)"

**Symptom**: `docker compose build` hangs or times out during `pip install`

**Solution**:
```bash
# Increase timeout
docker compose build --no-cache backend --build-arg TIMEOUT=300

# Or build with a different pip index
docker build \
  --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
  -f Dockerfile \
  -t skillbridge-main-backend:latest .

# Or use a different base image with pre-built wheels
# Edit Dockerfile to use: python:3.12-slim-bookworm (has apt-get, more tools)
```

---

## Issue: "Cannot connect to Docker daemon"

**Symptom**: `docker: command not found` or `Cannot connect to Docker daemon`

**Solution**:
```bash
# Check Docker is installed and running
docker --version

# If not installed, download Docker Desktop: https://www.docker.com/products/docker-desktop

# On Linux, Docker daemon may need to start
sudo systemctl start docker

# Check your user is in docker group (Linux)
groups | grep docker
sudo usermod -aG docker $USER
newgrp docker
```

---

## Issue: "Disk space: Docker images/volumes consuming too much space"

**Symptom**: `docker system df` shows 10GB+ used, disk filling up

**Solution**:
```bash
# See what's using space
docker system df

# Remove unused images, containers, volumes
docker system prune -a --volumes

# Or be more selective
docker volume prune              # Remove unused volumes
docker image prune -a            # Remove unused images
docker container prune           # Remove exited containers

# Nuclear option: reset everything (data will be lost)
docker system prune -a --volumes
docker compose down -v
docker compose up -d
```

---

## Issue: "Services won't communicate (backend can't reach frontend)"

**Symptom**: Frontend container can't curl `http://backend:8000`, says "name resolution failed"

**Causes**:
1. Services not on same network
2. Service name mismatch in docker-compose.yml
3. DNS cache stale

**Solution**:
```bash
# Verify network exists
docker network ls | grep skillbridge

# Verify services are connected
docker network inspect skillbridge-main_skillbridge

# Restart to refresh DNS
docker compose restart

# Or recreate network
docker compose down
docker compose up -d
```

---

## Issue: "Permission denied: Cannot write to mounted volume"

**Symptom**: Backend crashes with "Permission denied" when trying to create `/app/data/skillbridge.db`

**Solution**:
```bash
# Check volume permissions
docker compose exec backend ls -la /app/data/

# Ensure appuser (UID 1000) owns the directory
docker compose exec backend stat /app/data/ | grep Access

# Fix via Dockerfile (rebuild)
# Dockerfile already has: RUN mkdir -p /app/data && chown -R appuser:appuser /app/data
# If still broken, do manual fix:
docker compose exec backend sh -c "chmod 755 /app/data"
docker compose restart backend
```

---

## Getting Help

1. **Check logs first**: `docker compose logs -f`
2. **Verify all services are running**: `docker compose ps`
3. **Rebuild from scratch**: `docker compose down -v && docker compose up -d --build`
4. **Check GitHub Issues**: SkillBridge repo for similar problems
5. **Ask in Discord**: Link to project Discord/Slack

---

**Last Updated**: 2024-08-30

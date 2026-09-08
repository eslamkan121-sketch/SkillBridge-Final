# SkillBridge Dev Container Setup

## Quick Start

1. **Open in Dev Container**
   - Open the project folder in VS Code
   - Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
   - Run: `Dev Containers: Reopen in Container`
   - Wait for the container to build and start (2-5 minutes first time)

2. **Set Environment Variables**
   ```bash
   cp .devcontainer/.env.example .env
   # Edit .env with your ANTHROPIC_API_KEY and other secrets
   ```

3. **Services Running**
   - **Backend API**: `http://localhost:8000` (auto-reloads on file changes)
   - **Frontend Dev**: `http://localhost:3000` (Vite hot reload)
   - **PostgreSQL**: `localhost:5432` (credentials in .env)

## What's Installed

- **Python 3.12** with pip, virtualenv
- **Node.js 22** with npm
- **Docker CLI** (to run Docker commands inside the container)
- **Git & GitHub CLI**
- **VS Code Extensions**:
  - Docker tools
  - Python + Pylance (type checking)
  - TypeScript + Prettier
  - ESLint (JS/TS linting)
  - Ruff (Python linting)
  - GitLens (git history)

## Common Commands

### Backend
```bash
# Run tests
cd backend && pytest -xvs

# Run a specific test
pytest tests/test_auth.py -xvs

# Type check
pyright backend/

# Format code
black backend/ --line-length 100
```

### Frontend
```bash
cd frontend

# Dev server (already running, port 3000)
npm run dev

# Build for production
npm run build

# Type check
npm run typecheck

# Format code
npm exec prettier -- --write src/
```

### Database
```bash
# Connect to PostgreSQL
psql -h localhost -U postgres -d skillbridge

# Seed database (from backend/)
python -m backend.seed
```

## Debugging

### Backend Debugging
1. Set breakpoint in Python file
2. Run: `Python: Debug Python File` or use the Debug view (Ctrl+Shift+D)
3. Inspector opens at breakpoint

### Frontend Debugging
1. Open browser DevTools (F12)
2. Set breakpoint in Sources tab
3. Interact with the app

### View Logs
```bash
# Backend logs
docker logs skillbridge-backend-dev -f

# Frontend logs
docker logs skillbridge-frontend-dev -f

# Database logs
docker logs skillbridge-db-dev -f
```

## Rebuilding Services

```bash
# Rebuild all containers
docker compose down -v && docker compose up -d

# Rebuild just backend
docker compose build --no-cache backend && docker compose up -d backend
```

## Stopping Dev Container

- Press `Ctrl+Shift+P` → `Dev Containers: Reopen Folder Locally` to exit
- Or `docker compose down` to stop services
- Data in PostgreSQL persists until you run `docker compose down -v`

## Troubleshooting

**Port already in use?**
```bash
# Kill process on port
lsof -ti:8000 | xargs kill -9  # macOS/Linux
netstat -ano | findstr :8000    # Windows
```

**Module not found errors?**
```bash
# Reinstall backend deps
pip install -r backend/requirements.txt

# Reinstall frontend deps
cd frontend && npm ci
```

**Database connection failed?**
```bash
# Check db is running
docker compose ps

# Restart db
docker compose restart db

# Check logs
docker logs skillbridge-db-dev
```

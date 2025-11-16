
1. check and implement following points:
- Automatic retry mechanisms with exponential backoff
- Detailed execution logs for debugging
- Health check endpoints for monitoring
- Graceful shutdown handling

2. add more documentations inside code where necessary

3. rename setting `app_name` with `redis_key_prefix` throughout the codebase and documentations

4. evaluate adding on_startup and on_shutdown hooks for task manager inside FastAPI app

5. evaluate something like run first or if missing, in order to run a task immediately on startup if it hasn't run yet today

6. evaluate possibility to add a custom exception handler

7. docs:
   - Learn
   - About (check also people)
   - Release Notes

8. review docs initial paragraph (the one between ---) and review file names style choice between - and _

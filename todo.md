
1. check and implement following points:
- Automatic retry mechanisms with exponential backoff
- Detailed execution logs for debugging
- Health check endpoints for monitoring
- Graceful shutdown handling

2. add more documentations inside code where necessary

3. evaluate adding on_startup and on_shutdown hooks for task manager inside FastAPI app

4. evaluate something like run first or if missing, in order to run a task immediately on startup if it hasn't run yet today

5. evaluate possibility to add a custom exception handler

6. docs:
   - Learn
   - About (check also people)
   - Release Notes

7. review docs initial paragraph (the one between ---) and review file names style choice between - and _

8. Possibility to manage tasks from api

9. Possibility to set different args for different tasks on the same function, from api and wrapper

10. Evaluate redis linked lists

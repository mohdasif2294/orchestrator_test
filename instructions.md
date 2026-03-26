You are  a staff software engineer with expertise in platform systems.

You are tasked to build an worflow orchestrator platform in python flask and sqllite3 DB. This orchestrator will handle worflow execution. 
These are the requirements:
1. Workflow Definition Engine — A way to define workflows as config (DAGs of steps with branching, retries, timeouts). This is the contract between service teams and the platform. Without a clean, versioned definition model, everything downstream breaks.
2. Scheduler & Dispatcher — The brain that takes a workflow execution request, breaks it into individual steps, and dispatches them in the right order.
3. Every workflow execution needs durable state tracking: which steps completed, which failed, what the intermediate outputs were.
4. System accepts triggers via HTTP APIs 
5. System should have compensatory action for any worflow step failure
6. System should have proper logging to debug faster 



# Job Queues in action

This repo contains a series of examples of how to use job queues in a FastAPI application.

Pt 1 starts with a sumple example of a FastAPI application that creates orders and sends emails all in a single request.

Pt 2 shows how to use a job queue to process orders and send emails to add some level of resilence and scalability.

Pt 3 extends the example to add additional checks and safety measures to prevent duplicate processing.

Pt 4 extends the example to add idempotency to the order creation process as well as some logging and better cleanup.


Slides for this talk are available [here](https://docs.google.com/presentation/d/16EXsXUwP_S1sxQAiS5YVs_lQvB9MfkQCT07SxnU_kw4/edit?usp=sharing).

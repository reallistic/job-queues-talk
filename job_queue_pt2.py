from redis import Redis
from fastapi import FastAPI
from pydantic import BaseModel

from rq import Queue, Retry


order_service = ...
customer_service = ...
payment_service = ...
message_service = ...
sku_service = ...


class OutOfInventoryError(Exception):
    pass


class OrderCreate(BaseModel):
    customer_id: int
    payment_method_id: str
    skus: list[str]


app = FastAPI()


redis_q = Queue(connection=Redis())


def create_order_job(customer_id: int, skus: list[str], payment_method_id: str):
    order_id = order_service.create_order(skus, customer_id)
    try:
        for sku in skus:
            sku_service.update_inventory(sku, order_id)
    except OutOfInventoryError:
        order_service.cancel_order(order_id)
        return
    redis_q.enqueue(
        process_payment_and_confirmation,
        order_id,
        customer_id,
        payment_method_id,
        retry=Retry(max=3),
    )


def process_payment_and_confirmation(
    order_id: int, customer_id: int, payment_method_id: str
):
    payment_service.process_payment(order_id, payment_method_id)
    customer = customer_service.get_customer(customer_id)
    message_service.send_order_confirmation(customer.email, order_id)


@app.post("/orders/")
async def create_order(order: OrderCreate):
    job = redis_q.enqueue(
        create_order_job,
        order.customer_id,
        order.skus,
        order.payment_method_id,
        retry=Retry(max=3),
    )

    return {"job_id": job.id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

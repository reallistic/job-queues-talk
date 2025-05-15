from redis import Redis
from fastapi import FastAPI
from pydantic import BaseModel

from rq import Queue, Retry


orders_db = ...
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


def create_order_job(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    if not order.order_id:
        order_id = order_service.create_order(order.skus, order.customer_id)
        orders_db.save_order_id(order_request_id, order_id)
    redis_q.enqueue(check_inventory, order_request_id, retry=Retry(max=3))


def check_inventory(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    try:
        for sku in order.skus:
            sku_service.update_inventory(sku, order.order_id)
    except OutOfInventoryError:
        order_service.cancel_order(order.order_id)
        orders_db.mark_order_failed(order_request_id)
        return
    redis_q.enqueue(process_payment, order_request_id, retry=Retry(max=3))


def process_payment(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    if not order.payment_id:
        payment_id = payment_service.process_payment(
            order.order_id, order.payment_method_id
        )
        orders_db.save_payment(order_request_id, payment_id)
    redis_q.enqueue(email_order_confirmation, order.order_id, retry=Retry(max=3))


def email_order_confirmation(order_id: int):
    order = orders_db.get_order(order_id)
    customer = customer_service.get_customer(order.customer_id)
    message_service.send_order_confirmation(customer.email, order_id)


@app.post("/orders/")
async def create_order(order: OrderCreate):
    order_request_id = orders_db.record_order(
        order.skus, order.customer_id, order.payment_method_id
    )
    job = redis_q.enqueue(create_order_job, order_request_id, retry=Retry(max=3))

    return {"order_request_id": order_request_id, "job_id": job.id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

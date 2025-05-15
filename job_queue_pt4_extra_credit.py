import logging
from redis import Redis
from fastapi import FastAPI
from pydantic import BaseModel

from rq import Queue, Retry

logger = logging.getLogger(__name__)


orders_db = ...
order_service = ...
customer_service = ...
payment_service = ...
message_service = ...
sku_service = ...


class PaymentDeclinedError(Exception):
    pass


class OutOfInventoryError(Exception):
    pass


class CreateOrderRequest(BaseModel):
    customer_id: int
    payment_method_id: str
    skus: list[str]
    idempotency_key: str


app = FastAPI()


redis_q = Queue(connection=Redis())


def _get_log_extras(order_request_id, order=None, sku=None):
    log_extra = {"order_request_id": order_request_id}
    if order:
        log_extra["customer_id"] = order.customer_id
        if order.order_id:
            log_extra["order_id"] = order.order_id
        if order.payment_id:
            log_extra["payment_id"] = order.payment_id
    if sku:
        log_extra["sku"] = sku
    return log_extra


def create_order_job(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    if not order.order_id:
        order_id = order_service.create_order(order.skus, order.customer_id)
        orders_db.save_order_id(order_request_id, order_id)
        logger.info(
            "Created order for request", extra=_get_log_extras(order_request_id, order)
        )
    redis_q.enqueue(check_inventory, order_request_id, retry=Retry(max=3))


def _check_inventory_sku(sku: str, order: Order, order_request_id: int):
    try:
        if not orders_db.has_processed_sku(sku, order_request_id):
            sku_service.update_inventory(sku, order.order_id)
            orders_db.mark_sku_processed(order_request_id, sku)
            logger.info(
                "Updated inventory for SKU",
                extra=_get_log_extras(order_request_id, order, sku=sku),
            )
    except OutOfInventoryError:
        logger.info(
            "Out of inventory",
            extra=_get_log_extras(order_request_id, order, sku=sku),
        )
        return False

    return True


def check_inventory(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    for sku in order.skus:
        if not _check_inventory_sku(sku, order, order_request_id):
            order_service.cancel_order(order.order_id)
            order = orders_db.mark_order_failed(order_request_id)
            return
    redis_q.enqueue(process_payment, order_request_id, retry=Retry(max=3))


def process_payment(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    if not order.payment_id:
        try:
            payment_id = payment_service.process_payment(
                order.order_id, order.payment_method_id
            )
            order = orders_db.save_payment(order_request_id, payment_id)
            logger.info(
                "Processed payment",
                extra=_get_log_extras(order_request_id, order),
            )
        except PaymentDeclinedError:
            order_service.cancel_order(order.order_id)
            order = orders_db.mark_order_failed(order_request_id)
            logger.info(
                "Payment declined",
                extra=_get_log_extras(order_request_id, order),
            )
            return
    redis_q.enqueue(email_order_confirmation, order_request_id, retry=Retry(max=3))


def email_order_confirmation(order_request_id: int):
    order = orders_db.get_order(order_request_id)
    customer = customer_service.get_customer(order.customer_id)
    message_id = message_service.send_order_confirmation(customer.email, order.order_id)
    order = orders_db.mark_email_sent(order_request_id, message_id)
    logger.info(
        "Email sent",
        extra=_get_log_extras(order_request_id, order, message_id),
    )


@app.post("/orders/")
async def create_order(order_request: CreateOrderRequest):
    order = orders_db.record_order(
        order_request.idempotency_key,
        order_request.skus,
        order_request.customer_id,
        order_request.payment_method_id,
    )
    if not order.job_id:
        job = redis_q.enqueue(create_order_job, order.id, retry=Retry(max=3))
        order = orders_db.save_job_id(order.id, job.id)

    return {"order_request_id": order.id, "job_id": order.job_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

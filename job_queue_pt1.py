from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

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


@app.post("/orders/")
async def create_order(order: OrderCreate):
    order_id = order_service.create_order(order.skus, order.customer_id)
    try:
        for sku in order.skus:
            sku_service.update_inventory(sku, order_id)
    except OutOfInventoryError:
        order_service.cancel_order(order_id)
        return {"order_id": order_id, "error": "Out of inventory"}
    payment_id = payment_service.process_payment(order_id, order.payment_method_id)
    customer = customer_service.get_customer(order.customer_id)
    message_service.send_order_confirmation(customer.email, order_id)

    return {
        "order_id": order_id,
        "customer_id": order.customer_id,
        "payment_id": payment_id,
        "skus": order.skus,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

from typing import Annotated

from fastapi import Depends, Request

from app.integrations.odoo.client import OdooClient


def get_odoo_client(request: Request) -> OdooClient:
    return request.app.state.odoo_client


def get_request_id(request: Request) -> str:
    return request.state.request_id


OdooClientDependency = Annotated[OdooClient, Depends(get_odoo_client)]
RequestIdDependency = Annotated[str, Depends(get_request_id)]

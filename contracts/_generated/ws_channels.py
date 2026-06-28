"""GENERATED FILE — do not edit by hand.

Source: contracts/schema/ws-channels.yaml
Generator: contracts/codegen/gen-python.py
Regenerate: cd contracts && python codegen/gen-python.py
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

class PtyClientToServer1V0(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["resize"]
    rows: int
    cols: int


class PtyClientToServer1V1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping"]
    ts: int  # client epoch ms (= pong で echo back)


PtyClientToServer1 = Union[PtyClientToServer1V0, PtyClientToServer1V1]

class PtyServerToClient1V0(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["exit", "error"]
    message: Optional[str] = None


class PtyServerToClient1V1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["pong"]
    ts: int  # client から受信した ts を echo


PtyServerToClient1 = Union[PtyServerToClient1V0, PtyServerToClient1V1]

class ViewsClientToServer0V0(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sid: Optional[str] = None  # null = 全タブ非表示


class ViewsClientToServer0V1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["stop"]
    sid: str


ViewsClientToServer0 = Union[ViewsClientToServer0V0, ViewsClientToServer0V1]


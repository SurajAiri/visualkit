from typing import Literal


# class A:
#     a: str = "a"


# class B(A):
#     a: Literal["b"] = "b"


from abc import ABC, abstractmethod


class A:
    @property
    @abstractmethod
    def a(self) -> str:
        return "a"


a = A()
a.a

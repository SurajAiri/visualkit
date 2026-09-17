from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from visualkit.models.clips.base import Source
from visualkit.models.clips.media import MediaClip
from visualkit.utils.time import Time


class Vehicles(BaseModel):
    name: str
    model: str


class Car(Vehicles):
    vehicle_type: Literal["car"] = Field(
        default="car",
        frozen=True,
    )


class Bike(Vehicles):
    vehicle_type: Literal["bike"] = Field(
        default="bike",
        frozen=True,
    )


# Discriminated union
Vech = Annotated[
    Car | Bike,
    Field(discriminator="vehicle_type"),
]


# --------------------------------------------------
# Create models
# --------------------------------------------------

c = Car(
    name="Toyota",
    model="Camry",
)

b = Bike(
    name="Yamaha",
    model="R1",
)


# Automatically provided
print(c.vehicle_type)
# car

print(b.vehicle_type)
# bike


# --------------------------------------------------
# Cannot modify vehicle_type
# --------------------------------------------------

try:
    c.vehicle_type = "bike"
except Exception as e:
    print(type(e).__name__)
    print(e)


# --------------------------------------------------
# Serialize
# --------------------------------------------------

cj = c.model_dump_json(indent=2)
bj = b.model_dump_json(indent=2)

print(cj)
print(bj)


# --------------------------------------------------
# Deserialize using TypeAdapter
# --------------------------------------------------

adapter = TypeAdapter(Vech)

c1 = adapter.validate_json(cj)
b1 = adapter.validate_json(bj)


print(c1)
print(type(c1))
# Car

print(b1)
print(type(b1))
# Bike


# --------------------------------------------------
# It also discriminates regular dictionaries
# --------------------------------------------------

c2 = adapter.validate_python(
    {
        "name": "Toyota",
        "model": "Camry",
        "vehicle_type": "car",
    }
)

b2 = adapter.validate_python(
    {
        "name": "Yamaha",
        "model": "R1",
        "vehicle_type": "bike",
    }
)

print(type(c2))
# Car

print(type(b2))
# Bike


from visualkit.models.clips import CodedVisualClip, VisualContent, AudioContent

# cvc = CodedVisualClip(
#     id="coded1",
#     source=Source(source="code.py", start=Time.zero()),
# )

# mv = MediaClip(
#     id="media1",
#     source=Source(source="video.mp4", start=Time.zero()),
# )

# from pydantic import TypeAdapter

# adapter = TypeAdapter(VisualContent)
# adapter = TypeAdapter(AudioContent)

# cj = cvc.model_dump_json(indent=2)
# mj = mv.model_dump_json(indent=2)

# c1 = adapter.validate_json(cj)
# m1 = adapter.validate_json(mj)

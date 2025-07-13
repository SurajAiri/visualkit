from visualkit.media_element import MediaElement


class Timeline:
    def __init__(self):
        self.elements = []

    def add_element(self, element, start_time: float, end_time: float):
        if start_time >= end_time:
            raise ValueError("Start time must be less than end time")
        self.elements.append(
            {"element": element, "start_time": start_time, "end_time": end_time}
        )
        self.elements.sort(key=lambda x: x["start_time"])

    def get_active_element(self, timestamp: float):
        for elem_info in self.elements:
            if elem_info["start_time"] <= timestamp <= elem_info["end_time"]:
                return elem_info
        return None

    def get_duration(self) -> float:
        if not self.elements:
            return 0.0
        return max(elem["end_time"] for elem in self.elements)

    def get_previous_media_element(self, current_start_time: float):
        candidates = []
        for elem_info in self.elements:
            if elem_info["end_time"] <= current_start_time and isinstance(
                elem_info["element"], MediaElement
            ):
                candidates.append(elem_info)
        if candidates:
            return max(candidates, key=lambda x: x["end_time"])
        return None

    def get_next_media_element(self, current_end_time: float):
        candidates = []
        for elem_info in self.elements:
            if elem_info["start_time"] >= current_end_time and isinstance(
                elem_info["element"], MediaElement
            ):
                candidates.append(elem_info)
        if candidates:
            return min(candidates, key=lambda x: x["start_time"])
        return None

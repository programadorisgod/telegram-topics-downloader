import sys

from main import extract_topic_id


class ReplyTo:
    def __init__(self, top=None, msg=None):
        self.reply_to_top_id = top
        self.reply_to_msg_id = msg


class Msg:
    def __init__(self, reply_to):
        self.reply_to = reply_to


assert extract_topic_id(Msg(ReplyTo(top=0))) == 0, "reply dentro de General -> topic 0"
assert extract_topic_id(Msg(ReplyTo(top=7))) == 7, "reply dentro de topic 7"
assert extract_topic_id(Msg(ReplyTo(msg=42))) == 42, "reply suelto fuera de foro"
assert extract_topic_id(Msg(None)) is None, "sin reply -> None (General)"
print("ok")
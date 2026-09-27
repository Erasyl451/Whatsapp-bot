from neonize.client import NewClient
from neonize.events import Event, MessageEv, ConnectedEv, event
from neonize.utils import build_jid
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message

client = NewClient("whatsapp_session.db")

@client.event(MessageEv)
def on_group_message(client: NewClient, event: MessageEv):
    chat_obj = event.Info.MessageSource.Chat
    if hasattr(chat_obj, "User") and hasattr(chat_obj, "Server"):
        chat_jid = f"{chat_obj.User}@{chat_obj.Server}"
    else:
        chat_jid = str(chat_obj)

    # Очищаем JID от служебных символов gRPC
    if "User:" in chat_jid:
        import re
        user_match = re.search(r'User:\s*"([^\"]+)"', chat_jid)
        server_match = re.search(r'Server:\s*"([^\"]+)"', chat_jid)
        if user_match and server_match:
            chat_jid = f"{user_match.group(1)}@{server_match.group(2)}"
    #print(f"Получено сообщение от: {event.Info.MessageSource.Chat.User}, в: {chat_jid} JID: {event.Info.Pushname}, Сообщение: {event.Message.conversation or event.Message.extendedTextMessage.text}")
    print(event)

#code = client.PairPhone("77053238499", show_push_notification=True)
#print(f"Код для подтверждения: {code}")
client.connect()

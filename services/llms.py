
from xmlrpc import client
import streamlit as st
from openai import OpenAI

# Initialize the client HERE, so this file owns it
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

def process_with_ai(text, task_type, target_lang):
    if task_type == "translate_only":
        system_instruction = f"""
        Profesyonel tercüman gibi düşün.
        Aşağıdaki yazı metni muhtemelen Danca, İngilizce, Türkçe ya da Kallaalisut / Grönlandça.
        Lütfen bu yazıyı {target_lang} diline çevir.
        Özetleme, sadece çevir.
        Başa uyumlu bir emoji koy, başlığı ekle ve sonra metni çevir.
        Örnek:
        [Emoji Buraya] :soccer: [Başlık Buraya] Danimarka futbolunun yıldızı Christian Eriksen, Ukrayna maçında bir kez daha sahada fenalaşarak yere yığıldı. [Metin Buraya] Maç iptal edilirken, Danimarka Futbol Federasyonu oyuncunun bilincinin açık olduğunu duyurdu.

        Eğer kullanılan herhangi bir terim Danimarka'da 1 seneden az süredir yaşayan birinin anlayamayacağı türden ise, o terimi de açıklayarak çevir.
        Örnek:
        > Studenterkørsel: Öğrenci aracı. Liseli öğrencilerin mezun oldukları zaman bu araçları kiralayarak kutlamalar yaparlar.
        """
    else: 
        system_instruction = f"""
        Profesyonel bir redaktör gibi düşün.
        Aşağıdaki yazı metni muhtemelen Danca, İngilizce, Türkçe ya da Kallaalisut / Grönlandça.
        Yazıyı analiz et.
        Danimarka'da yaşayan bir T.C. vatandaşının perspektifinden bu konuyu değerlendir.
        Bundan sonra {target_lang} dilinde bir analiz hazırla.
        Başa uyumlu bir emoji koy, çarpıcı ve anlaşılır bir başlık ekle ve sonra alakadar eden detayları çevir.
        Başlıktan sonra en fazla 3 cümle yaz. Yani toplam 4 cümle olacak. 1 başlık + 3 cümle.
        Örnek:
        [Emoji Buraya] :soccer: [Başlık Buraya] Danimarka futbolunun yıldızı Christian Eriksen, Ukrayna maçında bir kez daha sahada fenalaşarak yere yığıldı. [Metin Buraya] Maç iptal edilirken, Danimarka Futbol Federasyonu oyuncunun bilincinin açık olduğunu duyurdu.
        Eğer kullanılan herhangi bir terim Danimarka'da 1 seneden az süredir yaşayan birinin anlayamayacağı türden ise, o terimi de açıklayarak çevir.
        Örnek:
        > Studenterkørsel: Öğrenci aracı. Liseli öğrencilerin mezun oldukları zaman bu araçları kiralayarak kutlamalar yaparlar.
        """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"**AI Error:** {e}"
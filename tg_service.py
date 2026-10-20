import sys
import io

# ضبط ترميز المخرجات لدعم العربية بدون مشاكل في موجه أوامر ويندوز
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import json
import asyncio
import re
import warnings

# كتم التحذيرات الجانبية
warnings.filterwarnings("ignore")

import mysql.connector
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types.auth import (
    SentCodeTypeSms,
    SentCodeTypeApp,
    SentCodeTypeCall,
    SentCodeTypeFlashCall
)
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    FloodWaitError,
    FreshResetAuthorisationForbiddenError,
    UserAlreadyParticipantError
)

API_ID = 38610044
API_HASH = '92cbd26110888597ac326bc6235d4b65'

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'tg_manager'
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def clean_phone_format(raw_phone):
    """استخراج الأرقام فقط بدون مسافات أو إشارات لتجنب مشاكل المقارنة"""
    digits = re.sub(r'\D', '', str(raw_phone))
    return digits

async def request_code(phone, force_sms=False):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        try:
            send_result = await client.send_code_request(formatted_phone, force_sms=force_sms)
        except TypeError:
            send_result = await client.send_code_request(formatted_phone)

        session_str = client.session.save()
        phone_code_hash = send_result.phone_code_hash
        code_type = getattr(send_result, 'type', None)

        if force_sms:
            if isinstance(code_type, SentCodeTypeSms):
                delivery_channel = "sms"
                msg = f"تم إرسال الكود بنجاح عبر رسالة نصية قصيرة (SMS) إلى {formatted_phone}"
            else:
                delivery_channel = "app"
                msg = f"تعذر إرسال SMS، وتم إرسال الكود انتقال إلى تطبيق تيليجرام"
        else:
            delivery_channel = "normal"
            msg = f"تم إرسال كود التحقق بنجاح إلى {formatted_phone}"

        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM numbers WHERE phone = %s OR phone = %s OR phone LIKE %s", 
                       (formatted_phone, pure_phone, f"%{pure_phone}%"))
        
        query = """
            INSERT INTO numbers (phone, session_string, phone_code_hash, status)
            VALUES (%s, %s, %s, 'pending')
        """
        cursor.execute(query, (formatted_phone, session_str, phone_code_hash))
        conn.commit()
        cursor.close()
        conn.close()

        print(json.dumps({
            "status": "success",
            "channel": delivery_channel,
            "message": msg
        }, ensure_ascii=False))

    except FloodWaitError as e:
        print(json.dumps({"status": "error", "message": f"تم حظر الرقم مؤقتاً بسبب تكرار المحاولات، يرجى الانتظار {e.seconds} ثانية"}, ensure_ascii=False))
    except PhoneNumberBannedError:
        print(json.dumps({"status": "error", "message": "هذا الرقم محظور من تيليجرام"}, ensure_ascii=False))
    except PhoneNumberInvalidError:
        print(json.dumps({"status": "error", "message": "رقم الهاتف غير صالح، تأكد من المفتاح الدولي"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ: {str(e)}"}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def verify_code(phone, code):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s)
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()

    if not row or not row.get('session_string'):
        print(json.dumps({"status": "error", "message": "لم يتم العثور على طلب معلق لهذا الرقم، يرجى طلب كود جديد"}, ensure_ascii=False))
        cursor.close()
        conn.close()
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        await client.sign_in(formatted_phone, str(code).strip(), phone_code_hash=row['phone_code_hash'])
        new_session = client.session.save()

        # جلب الاسم الحقيقي للحساب عند التسجيل
        me = await client.get_me()
        tg_full_name = f"{me.first_name or ''} {me.last_name or ''}".strip()

        cursor.execute("UPDATE numbers SET phone = %s, session_string = %s, telegram_name = %s, status = 'ready' WHERE id = %s", 
                       (formatted_phone, new_session, tg_full_name, row['id']))
        conn.commit()
        print(json.dumps({"status": "success", "telegram_name": tg_full_name, "message": "تم تأكيد الكود وحفظ الجلسة بنجاح!"}, ensure_ascii=False))
    except PhoneCodeExpiredError:
        print(json.dumps({"status": "error", "message": "انتهت صلاحية رمز التحقق، يرجى طلب كود جديد"}, ensure_ascii=False))
    except PhoneCodeInvalidError:
        print(json.dumps({"status": "error", "message": "رمز التحقق غير صحيح، تأكد من الأرقام"}, ensure_ascii=False))
    except SessionPasswordNeededError:
        print(json.dumps({"status": "error", "message": "الحساب محمي بكلمة سر خطوتين (2FA)"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ: {str(e)}"}, ensure_ascii=False))
    finally:
        cursor.close()
        conn.close()
        try:
            await client.disconnect()
        except Exception:
            pass

async def get_telegram_code(phone):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row or not row.get('session_string'):
        print(json.dumps({"status": "error", "message": "لم يتم العثور على جلسة جاهزة لهذا الرقم"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "error", "message": "الجلسة منتهية أو مسجلة خروج"}, ensure_ascii=False))
            return

        found_code = None
        try:
            async for msg in client.iter_messages(777000, limit=5):
                if msg.text:
                    match = re.search(r'\b(\d{5,6})\b', msg.text)
                    if match:
                        found_code = match.group(1)
                        break
        except Exception:
            pass

        if not found_code:
            async for dialog in client.iter_dialogs(limit=5):
                if dialog.id == 777000 or "telegram" in dialog.name.lower():
                    async for msg in client.iter_messages(dialog, limit=3):
                        if msg.text:
                            match = re.search(r'\b(\d{5,6})\b', msg.text)
                            if match:
                                found_code = match.group(1)
                                break
                if found_code:
                    break

        if found_code:
            print(json.dumps({"status": "success", "code": found_code}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "waiting", "message": "لم يصل كود جديد بعد، انتظر بضع ثوانٍ واضغط مجدداً"}, ensure_ascii=False))
            
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ داخلي: {str(e)}"}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def check_login_status(phone):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row or not row.get('session_string'):
        print(json.dumps({"status": "error", "logged_in": False, "message": "الجلسة غير متوفرة"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "error", "logged_in": False, "message": "الجلسة غير مسجلة"}, ensure_ascii=False))
            return

        is_logged = False
        async for msg in client.iter_messages(777000, limit=5):
            if msg.text:
                lower_text = msg.text.lower()
                if any(k in lower_text for k in ["login notification", "logged in", "دخول", "جهاز جديد", "new login"]):
                    is_logged = True
                    break

        if is_logged:
            print(json.dumps({"status": "success", "logged_in": True, "message": "تم تسجيل دخولك إلى الهاتف بنجاح"}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "waiting", "logged_in": False, "message": "لم يتم تأكيد الدخول من الهاتف بعد"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "logged_in": False, "message": str(e)}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def terminate_other_sessions(phone):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row or not row.get('session_string'):
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة في النظام"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "error", "message": "الجلسة غير مصرح لها"}, ensure_ascii=False))
            return

        from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest, ResetAuthorizationsRequest
        
        killed_count = 0
        error_detail = None

        try:
            authorizations_res = await client(GetAuthorizationsRequest())
            for auth in authorizations_res.authorizations:
                if not auth.current:
                    try:
                        await client(ResetAuthorizationRequest(hash=auth.hash))
                        killed_count += 1
                    except Exception as inner_e:
                        error_detail = str(inner_e)
        except Exception as get_err:
            error_detail = str(get_err)

        if killed_count == 0:
            try:
                await client(ResetAuthorizationsRequest())
                killed_count += 1
            except FreshResetAuthorisationForbiddenError:
                error_detail = "تيليجرام يتطلب مرور 24 ساعة على تثبيت الجلسة الأصلية قبل السماح بطرد الجلسات الأخرى"
            except Exception as reset_err:
                if not error_detail:
                    error_detail = str(reset_err)

        if killed_count > 0:
            print(json.dumps({
                "status": "success",
                "message": f"تم بنجاح طرد الأجهزة الدخيلة ({killed_count}) وإعادة الرقم متاحاً للمخزون"
            }, ensure_ascii=False))
        else:
            print(json.dumps({
                "status": "warning",
                "message": f"تم تصفير وقت السحب، لكن لم يتم طرد الجهاز: {error_detail or 'لا توجد أجهزة إضافية مسجلة'}"
            }, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ أثناء فحص الجلسات: {str(e)}"}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

# فحص سلامة الجلسة وجلب اسم الحساب الحالي في تيليجرام لمزامنته
async def check_session_health(phone):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row or not row.get('session_string'):
        print(json.dumps({"status": "dead", "label": "مفقودة", "telegram_name": "", "message": "لا توجد جلسة لهذا الرقم"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "dead", "label": "معطلة", "telegram_name": "", "message": "تم تسجيل الخروج من الحساب"}, ensure_ascii=False))
            return

        # استخراج الاسم الحقيقي الحالي للحساب
        me = await client.get_me()
        tg_full_name = f"{me.first_name or ''} {me.last_name or ''}".strip()

        has_spam = False
        spam_reason = "سليم وحر"
        try:
            bot = await client.get_input_entity("SpamBot")
            await client.send_message(bot, "/start")
            await asyncio.sleep(2)
            async for msg in client.iter_messages(bot, limit=2):
                txt = (msg.text or "").lower()
                if any(w in txt for w in ["good news", "free", "no limits", "أخبار سارة", "لا توجد قيود"]):
                    has_spam = False
                    break
                elif any(w in txt for w in ["limit", "sorry", "unfortunately", "للأسف", "تقييد", "سبام"]):
                    has_spam = True
                    spam_reason = "الحساب مقيد بسبام (SpamBlock)"
                    break
        except Exception:
            pass

        if has_spam:
            print(json.dumps({"status": "spam", "label": "مقيد (سبام)", "telegram_name": tg_full_name, "message": spam_reason}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "clean", "label": "سليمة ونشطة", "telegram_name": tg_full_name, "message": "الحساب سليم وجاهز تماماً"}, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"status": "dead", "label": "معطلة", "telegram_name": "", "message": str(e)}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def set_two_step_verification(phone, password, hint=""):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "error", "message": "الجلسة غير مصرح لها"}, ensure_ascii=False))
            return

        await client.edit_2fa(new_password=password, hint=hint)
        print(json.dumps({"status": "success", "message": f"تم تفعيل التحقق بخطوتين بنجاح بكلمة السر: {password}"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ: {str(e)}"}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def remove_two_step_verification(phone, current_password=""):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "error", "message": "الجلسة غير مصرح لها"}, ensure_ascii=False))
            return

        await client.edit_2fa(current_password=current_password if current_password else None, new_password=None)
        print(json.dumps({"status": "success", "message": "تم حذف التحقق بخطوتين بنجاح وإلغاء كلمة السر"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ: {str(e)}"}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def logout_session(phone):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE phone = %s OR phone = %s OR phone LIKE %s
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()

    if row and row.get('session_string'):
        client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()
        except Exception:
            pass
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    cursor.execute("DELETE FROM numbers WHERE phone = %s OR phone = %s OR phone LIKE %s", 
                   (formatted_phone, pure_phone, f"%{pure_phone}%"))
    conn.commit()
    cursor.close()
    conn.close()
    print(json.dumps({"status": "success", "message": "تم إنهاء الجلسة وحذفها بنجاح"}, ensure_ascii=False))

# --- دوال الأتمتة ---

async def change_profile_name(phone, first_name, last_name=""):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        from telethon.tl.functions.account import UpdateProfileRequest
        await client(UpdateProfileRequest(first_name=first_name, last_name=last_name))
        
        # حفظ الاسم الجديد في جدول قاعدة البيانات مباشرة
        full_new_name = f"{first_name} {last_name}".strip()
        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute("UPDATE numbers SET telegram_name = %s WHERE (phone = %s OR phone = %s OR phone LIKE %s)",
                     (full_new_name, formatted_phone, pure_phone, f"%{pure_phone}%"))
        conn2.commit()
        cur2.close()
        conn2.close()

        print(json.dumps({"status": "success", "telegram_name": full_new_name, "message": f"تم تحديث الاسم إلى {full_new_name}"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def change_profile_photo(phone, photo_path):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        from telethon.tl.functions.photos import UploadProfilePhotoRequest
        file = await client.upload_file(photo_path)
        await client(UploadProfilePhotoRequest(fallback=False, file=file))
        print(json.dumps({"status": "success", "message": "تم تعيين الصورة الشخصية بنجاح"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

async def handle_bot_referral(phone, ref_link):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة"}, ensure_ascii=False))
        return

    bot_match = re.search(r'(?:t\.me/|@)([a-zA-Z0-9_]+)(?:\?start=(.+))?', ref_link)
    if not bot_match:
        print(json.dumps({"status": "error", "message": "رابط الإحالة غير صالح"}, ensure_ascii=False))
        return

    bot_username = bot_match.group(1)
    start_param = bot_match.group(2) if bot_match.group(2) else ""

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest

        bot_entity = await client.get_input_entity(bot_username)
        if start_param:
            await client.send_message(bot_entity, f"/start {start_param}")
        else:
            await client.send_message(bot_entity, "/start")

        await asyncio.sleep(2)

        joined_count = 0
        async for msg in client.iter_messages(bot_entity, limit=3):
            if msg.text:
                channels = re.findall(r'(?:https?://)?t\.me/([a-zA-Z0-9_+]+)', msg.text)
                for ch in channels:
                    if ch.lower() != bot_username.lower():
                        try:
                            if ch.startswith('+') or 'joinchat' in ch:
                                clean_hash = ch.replace('+', '').replace('joinchat/', '')
                                await client(ImportChatInviteRequest(clean_hash))
                            else:
                                await client(JoinChannelRequest(ch))
                            joined_count += 1
                        except:
                            pass

            if msg.buttons:
                for row_btn in msg.buttons:
                    for btn in row_btn:
                        if hasattr(btn, 'url') and btn.url:
                            ch_match = re.search(r't\.me/([a-zA-Z0-9_+]+)', btn.url)
                            if ch_match and ch_match.group(1).lower() != bot_username.lower():
                                try:
                                    ch_name = ch_match.group(1)
                                    if ch_name.startswith('+'):
                                        await client(ImportChatInviteRequest(ch_name.replace('+', '')))
                                    else:
                                        await client(JoinChannelRequest(ch_name))
                                    joined_count += 1
                                except:
                                    pass

                for row_btn in msg.buttons:
                    for btn in row_btn:
                        btn_txt = btn.text.lower() if btn.text else ""
                        if any(w in btn_txt for w in ['تحقق', 'تأكيد', 'انضممت', 'اشتركت', 'check', 'joined', 'done', 'continue']):
                            try:
                                await btn.click()
                                await asyncio.sleep(1)
                            except:
                                pass

        print(json.dumps({
            "status": "success",
            "message": f"تم إرسال الإحالة بنجاح والانضمام لـ ({joined_count}) قناة إجبارية"
        }, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"status": "error", "message": f"خطأ: {str(e)}"}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

# الدالة الجديدة: الانضمام لقناة أو مجموعة
async def handle_join_channel(phone, channel_raw):
    pure_phone = clean_phone_format(phone)
    formatted_phone = '+' + pure_phone
    
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT session_string FROM numbers 
        WHERE (phone = %s OR phone = %s OR phone LIKE %s) AND status = 'ready'
        ORDER BY id DESC LIMIT 1
    """, (formatted_phone, pure_phone, f"%{pure_phone}%"))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row or not row.get('session_string'):
        print(json.dumps({"status": "error", "message": "الجلسة غير متوفرة في النظام"}, ensure_ascii=False))
        return

    target = channel_raw.strip()
    if not target:
        print(json.dumps({"status": "error", "message": "رابط أو معرف القناة فارغ"}, ensure_ascii=False))
        return

    client = TelegramClient(StringSession(row['session_string']), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print(json.dumps({"status": "error", "message": "الجلسة غير مصرح لها أو منتهية"}, ensure_ascii=False))
            return

        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.tl.functions.messages import ImportChatInviteRequest

        # فحص إن كان الرابط خاصاً (دعوة خاصة)
        if '+' in target or 'joinchat' in target:
            clean_hash = target.split('+')[-1].split('/')[-1] if '+' in target else target.split('joinchat/')[-1].split('/')[0]
            clean_hash = clean_hash.replace('+', '').strip()
            try:
                await client(ImportChatInviteRequest(clean_hash))
                print(json.dumps({"status": "success", "message": "تم الانضمام للقناة الخاصة بنجاح!"}, ensure_ascii=False))
            except UserAlreadyParticipantError:
                print(json.dumps({"status": "success", "message": "الحساب منضم بالفعل لهذه القناة"}, ensure_ascii=False))
        else:
            # تنظيف الرابط العام لاستخراج المعرف فقط
            clean_username = re.sub(r'^(https?:\/\/)?(www\.)?(t\.me\/|telegram\.me\/)', '', target).strip().replace('@', '')
            try:
                await client(JoinChannelRequest(clean_username))
                print(json.dumps({"status": "success", "message": f"تم الانضمام للقناة @{clean_username} بنجاح!"}, ensure_ascii=False))
            except UserAlreadyParticipantError:
                print(json.dumps({"status": "success", "message": "الحساب منضم بالفعل لهذه القناة"}, ensure_ascii=False))

    except FloodWaitError as fe:
        print(json.dumps({"status": "error", "message": f"تقييد مؤقت بسبب تكرار الانضمام، انتظر {fe.seconds} ثانية"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit(1)

    action = sys.argv[1]
    phone = sys.argv[2]
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        if action == 'request_code':
            force = len(sys.argv) > 3 and sys.argv[3] == '1'
            loop.run_until_complete(request_code(phone, force))
        elif action == 'verify_code':
            code = sys.argv[3]
            loop.run_until_complete(verify_code(phone, code))
        elif action == 'get_code':
            loop.run_until_complete(get_telegram_code(phone))
        elif action == 'check_login':
            loop.run_until_complete(check_login_status(phone))
        elif action == 'logout':
            loop.run_until_complete(logout_session(phone))
        elif action == 'terminate_others':
            loop.run_until_complete(terminate_other_sessions(phone))
        elif action == 'check_health':
            loop.run_until_complete(check_session_health(phone))
        elif action == 'set_2fa':
            pwd = sys.argv[3]
            hint = sys.argv[4] if len(sys.argv) > 4 else ""
            loop.run_until_complete(set_two_step_verification(phone, pwd, hint))
        elif action == 'remove_2fa':
            cur_pwd = sys.argv[3] if len(sys.argv) > 3 else ""
            loop.run_until_complete(remove_two_step_verification(phone, cur_pwd))
        elif action == 'change_name':
            first = sys.argv[3]
            last = sys.argv[4] if len(sys.argv) > 4 else ""
            loop.run_until_complete(change_profile_name(phone, first, last))
        elif action == 'change_photo':
            photo = sys.argv[3]
            loop.run_until_complete(change_profile_photo(phone, photo))
        elif action == 'bot_referral':
            ref = sys.argv[3]
            loop.run_until_complete(handle_bot_referral(phone, ref))
        elif action == 'join_channel':
            channel_param = sys.argv[3]
            loop.run_until_complete(handle_join_channel(phone, channel_param))
    except Exception as general_err:
        print(json.dumps({"status": "error", "message": f"خطأ عام بالنظام: {str(general_err)}"}, ensure_ascii=False))
# PhysioExpertPro – Staging Secure Package v2

- هذه الحزمة مبنية على `app.py` والواجهات التسع التي أرسلتها.
- انسخ `app.py` و`clinical_models.py` ومجلدات `templates/` و`data/` و`scripts/` إلى فرع `feature/exercise-images-staging` فقط بعد مراجعة التغييرات.
- استخدم ملف `requirements.txt` المرفق في هذه الحزمة على Staging فقط؛ يحتوي على إصدارات مثبتة ويستبدل الاعتماد القديم على `google-generativeai` بـ `google-genai`.
- في Render لخدمة `physioexpertpro-staging` فقط: تأكد من قاعدة Staging، وضع SECRET_KEY قويًا، وأضف `CLINICAL_IMPORT_TARGET=staging`.
- شغّل المعاينة فقط أولًا. لا تنفذ الاستيراد الفعلي قبل مراجعة السجلات والتحقق من اسم قاعدة البيانات.
- لا ترفع هذه النسخة إلى Production.

لم يتم الاتصال بـ GitHub أو Render ولم يتم تعديل أي قاعدة بيانات.


## تحديث المكتبات وGemini في v3
- تم تثبيت إصدارات المكتبات المباشرة في `requirements.txt`.
- تم نقل تكامل Gemini إلى `google-genai` باستخدام `genai.Client` و`client.models.generate_content`.
- اسم النموذج الافتراضي أصبح `gemini-flash-latest`، ويمكن تغييره من متغير البيئة `GEMINI_MODEL` في خدمة Staging فقط.
- تم استبدال Bleach بـ `nh3` لتعقيم HTML.
- تم الإبقاء على `psycopg2-binary` فقط لأن رابط PostgreSQL الحالي بصيغة `postgresql://`، وحذف `psycopg[binary]` لتجنب وجود مشغلين متنافسين.
- لا تنشر هذه الحزمة على Production. اختبر Staging أولاً، خصوصاً توليد بروتوكول Gemini، تسجيل الدخول، الاستيراد والتصدير Excel، واتصال قاعدة البيانات.

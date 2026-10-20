<?php
header('Content-Type: application/json; charset=utf-8');

$host = 'localhost';
$db   = 'tg_manager';
$user = 'root';
$pass = '';

try {
    $pdo = new PDO("mysql:host=$host;dbname=$db;charset=utf8mb4", $user, $pass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
    ]);
} catch (Exception $e) {
    echo json_encode(["status" => "error", "message" => "فشل الاتصال بقاعدة البيانات: " . $e->getMessage()]);
    exit;
}

// بيانات بوت النسخ الاحتياطي
define('BACKUP_BOT_TOKEN', '8585399651:AAHsu2Xo0ztVflFKzNkguP9_lyw6cB9RrQU');
define('BACKUP_CHAT_ID', '8936129209');

function extract_clean_json($raw) {
    if (empty($raw)) return null;
    if (preg_match('/\{[\s\S]*\}/', $raw, $matches)) {
        return $matches[0];
    }
    return null;
}

// دالة توليد ملف النسخ الاحتياطي ZIP شاملاً قاعدة البيانات
function generate_project_backup_zip($pdo) {
    if (!class_exists('ZipArchive')) {
        return ["status" => "error", "message" => "مكتبة ZipArchive غير مفعلة في سيرفر PHP لديك"];
    }

    $projectDir = __DIR__;
    $backupFileName = "tg_manager_backup_" . date('Y-m-d_H-i-s') . ".zip";
    $zipPath = sys_get_temp_dir() . DIRECTORY_SEPARATOR . $backupFileName;

    $zip = new ZipArchive();
    if ($zip->open($zipPath, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== TRUE) {
        return ["status" => "error", "message" => "تعذر إنشاء ملف الـ ZIP المؤقت"];
    }

    // 1. تصدير جدول قاعدة البيانات SQL
    $sqlDump = "-- نسخة احتياطية لقاعدة البيانات tg_manager\n-- التاريخ: " . date('Y-m-d H:i:s') . "\n\n";
    $sqlDump .= "CREATE TABLE IF NOT EXISTS `numbers` (\n";
    $sqlDump .= "  `id` int(11) NOT NULL AUTO_INCREMENT,\n";
    $sqlDump .= "  `phone` varchar(30) NOT NULL,\n";
    $sqlDump .= "  `session_name` varchar(255) DEFAULT NULL,\n";
    $sqlDump .= "  `telegram_name` varchar(255) DEFAULT '',\n";
    $sqlDump .= "  `health_status` varchar(20) DEFAULT 'clean',\n";
    $sqlDump .= "  `two_fa_password` varchar(255) DEFAULT '',\n";
    $sqlDump .= "  `session_string` text DEFAULT NULL,\n";
    $sqlDump .= "  `phone_code_hash` varchar(255) DEFAULT NULL,\n";
    $sqlDump .= "  `status` varchar(20) DEFAULT 'pending',\n";
    $sqlDump .= "  `logged_in_at` datetime DEFAULT NULL,\n";
    $sqlDump .= "  `expire_at` datetime DEFAULT NULL,\n";
    $sqlDump .= "  PRIMARY KEY (`id`)\n";
    $sqlDump .= ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n\n";

    try {
        $rows = $pdo->query("SELECT * FROM numbers")->fetchAll(PDO::FETCH_ASSOC);
        if ($rows) {
            foreach ($rows as $r) {
                $cols = array_map(function($c) { return "`$c`"; }, array_keys($r));
                $vals = array_map(function($v) use ($pdo) {
                    return $v === null ? 'NULL' : $pdo->quote($v);
                }, array_values($r));
                $sqlDump .= "INSERT INTO `numbers` (" . implode(', ', $cols) . ") VALUES (" . implode(', ', $vals) . ");\n";
            }
        }
    } catch(Exception $ex) {}

    $zip->addFromString('database_tg_manager.sql', $sqlDump);

    // 2. تجميع ملفات المشروع (تجاهل ملفات zip السابقة والمجلدات المؤقتة)
    $files = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($projectDir, RecursiveDirectoryIterator::SKIP_DOTS),
        RecursiveIteratorIterator::LEAVES_ONLY
    );

    foreach ($files as $file) {
        if ($file->isDir()) continue;
        $filePath = $file->getRealPath();
        $relativePath = substr($filePath, strlen($projectDir) + 1);

        // تخطي مجلدات التخزين المؤقتة أو ملفات الباك اب السابقة
        if (strpos($relativePath, '.git') !== false || 
            strpos($relativePath, 'node_modules') !== false ||
            preg_match('/\.zip$/i', $relativePath)) {
            continue;
        }

        $zip->addFile($filePath, $relativePath);
    }

    $zip->close();
    return ["status" => "success", "file_path" => $zipPath, "file_name" => $backupFileName];
}

// تنظيف الجلسات المنتهية الصلاحية تلقائياً بعد مرور ساعة
$expiredCheck = $pdo->query("SELECT phone FROM numbers WHERE expire_at IS NOT NULL AND expire_at <= NOW()");
while ($exp = $expiredCheck->fetch()) {
    $p = escapeshellarg($exp['phone']);
    shell_exec("python tg_service.py logout $p 2>&1");
    $cleanP = preg_replace('/\D/', '', $exp['phone']);
    $pdo->prepare("DELETE FROM numbers WHERE phone = ? OR phone LIKE ?")->execute([$exp['phone'], "%$cleanP%"]);
}

$action = $_GET['action'] ?? '';

switch ($action) {
    // 1. تنزيل النسخة الاحتياطية مباشرة للكمبيوتر
    case 'backup_download':
        $res = generate_project_backup_zip($pdo);
        if ($res['status'] !== 'success') {
            echo json_encode($res, JSON_UNESCAPED_UNICODE);
            exit;
        }

        $file = $res['file_path'];
        $filename = $res['file_name'];

        if (file_exists($file)) {
            header('Content-Description: File Transfer');
            header('Content-Type: application/zip');
            header('Content-Disposition: attachment; filename="' . $filename . '"');
            header('Expires: 0');
            header('Cache-Control: must-revalidate');
            header('Pragma: public');
            header('Content-Length: ' . filesize($file));
            readfile($file);
            @unlink($file);
            exit;
        } else {
            echo json_encode(["status" => "error", "message" => "الملف غير موجود"], JSON_UNESCAPED_UNICODE);
            exit;
        }
        break;

    // 2. إرسال النسخة الاحتياطية عبر بوت تيليجرام
    case 'backup_telegram':
        $res = generate_project_backup_zip($pdo);
        if ($res['status'] !== 'success') {
            echo json_encode($res, JSON_UNESCAPED_UNICODE);
            exit;
        }

        $file = $res['file_path'];
        $filename = $res['file_name'];
        $fileSizeMB = round(filesize($file) / (1024 * 1024), 2);

        $caption = "📦 *نسخة احتياطية جديدة لمشروع السفاح الشمالي*\n\n"
                 . "📅 التاريخ: " . date('Y-m-d H:i:s') . "\n"
                 . "💾 حجم الملف: " . $fileSizeMB . " MB\n"
                 . "✅ تشمل: ملفات البرمجة (PHP, Python, JS, HTML, CSS) + تفريغ قاعدة البيانات الكامل.";

        $url = "https://api.telegram.org/bot" . BACKUP_BOT_TOKEN . "/sendDocument";
        $postFields = [
            'chat_id' => BACKUP_CHAT_ID,
            'caption' => $caption,
            'parse_mode' => 'Markdown',
            'document' => new CURLFile($file, 'application/zip', $filename)
        ];

        $ch = curl_init();
        curl_setopt($ch, CURLOPT_URL, $url);
        curl_setopt($ch, CURLOPT_POST, 1);
        curl_setopt($ch, CURLOPT_POSTFIELDS, $postFields);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
        $tgResponse = curl_exec($ch);
        $curlErr = curl_error($ch);
        curl_close($ch);

        @unlink($file);

        if ($curlErr) {
            echo json_encode(["status" => "error", "message" => "فشل إرسال التيليجرام: " . $curlErr], JSON_UNESCAPED_UNICODE);
        } else {
            $parsed = json_decode($tgResponse, true);
            if ($parsed && isset($parsed['ok']) && $parsed['ok']) {
                echo json_encode(["status" => "success", "message" => "تم إرسال النسخة الاحتياطية بالكامل إلى التيليجرام بنجاح! 🚀"], JSON_UNESCAPED_UNICODE);
            } else {
                $errDesc = $parsed['description'] ?? 'فشل إرسال البوت، تأكد من إرسال /start للبوت أولاً';
                echo json_encode(["status" => "error", "message" => "خطأ من تيليجرام: " . $errDesc], JSON_UNESCAPED_UNICODE);
            }
        }
        break;

    case 'request_code':
        $phone = urldecode($_GET['phone'] ?? '');
        $cleanP = preg_replace('/\D/', '', $phone);

        // فحص وجود الجلسة مسبقاً وتنبيه المستخدم
        $checkStmt = $pdo->prepare("SELECT id, session_name FROM numbers WHERE (phone = ? OR phone LIKE ?) AND status = 'ready' LIMIT 1");
        $checkStmt->execute([$phone, "%$cleanP%"]);
        $existing = $checkStmt->fetch();

        if ($existing) {
            $nameStr = !empty($existing['session_name']) ? " (" . $existing['session_name'] . ")" : "";
            echo json_encode([
                "status" => "error",
                "message" => "الجلسة موجودة عندك مسبقاً{$nameStr}، لا تطلب كود لهذا الرقم!"
            ], JSON_UNESCAPED_UNICODE);
            exit;
        }

        $force_sms = $_GET['force_sms'] ?? '0';
        $cmd = "python tg_service.py request_code " . escapeshellarg($phone) . " " . escapeshellarg($force_sms) . " 2>&1";
        $raw = shell_exec($cmd);
        $cleanJson = extract_clean_json($raw);
        
        if ($cleanJson !== null && json_decode($cleanJson, true) !== null) {
            echo $cleanJson;
        } else {
            echo json_encode([
                "status" => "error", 
                "message" => !empty(trim($raw)) ? trim($raw) : "لم يصدر رد من سكريبت بايثون"
            ], JSON_UNESCAPED_UNICODE);
        }
        break;

    case 'verify_code':
        $phone = urldecode($_GET['phone'] ?? '');
        $code = trim($_GET['code'] ?? '');
        $cmd = "python tg_service.py verify_code " . escapeshellarg($phone) . " " . escapeshellarg($code) . " 2>&1";
        $raw = shell_exec($cmd);
        $cleanJson = extract_clean_json($raw);
        $res = json_decode($cleanJson, true);

        if ($res && isset($res['status']) &&$res['status'] === 'success') {
            $cleanP = preg_replace('/\D/', '',$phone);
            
            // حساب الترقيم التسلسلي التالي تلقائياً
            $countStmt =$pdo->query("SELECT COUNT(*) AS total FROM numbers WHERE status = 'ready'");
            $totalCount = (int)$countStmt->fetch()['total'];
            $nextIndex =$totalCount;
            if ($nextIndex < 1)$nextIndex = 1;
            
            $sessionTitle = "السفاح الشمالي " . $nextIndex;
            $updateName =$pdo->prepare("UPDATE numbers SET session_name = ? WHERE (phone = ? OR phone LIKE ?) AND (session_name IS NULL OR session_name = '')");
            $updateName->execute([$sessionTitle, $phone, "%$cleanP%"]);

            echo json_encode(["status" => "success", "output" => "تم تأكيد الكود وحفظ الجلسة بنجاح باسم [{$sessionTitle}]!"], JSON_UNESCAPED_UNICODE);
        } else {
            echo json_encode(["status" => "error", "output" => $res['message'] ?? $raw], JSON_UNESCAPED_UNICODE);
        }
        break;

    case 'list_numbers':
        // التأكد من وجود الأعمدة المطلوبة
        try {
            $pdo->query("SELECT health_status, telegram_name, two_fa_password FROM numbers LIMIT 1");
        } catch (Exception $e) {
            try { $pdo->exec("ALTER TABLE numbers ADD COLUMN health_status VARCHAR(20) DEFAULT 'clean'"); } catch(Exception $ex){}
            try { $pdo->exec("ALTER TABLE numbers ADD COLUMN telegram_name VARCHAR(255) DEFAULT ''"); } catch(Exception $ex){}
            try { $pdo->exec("ALTER TABLE numbers ADD COLUMN two_fa_password VARCHAR(255) DEFAULT ''"); } catch(Exception $ex){}
        }

        $stmt =$pdo->query("SELECT id, phone, session_name, telegram_name, status, health_status, logged_in_at, expire_at FROM numbers WHERE status = 'ready' ORDER BY id ASC");
        $rows = $stmt->fetchAll();$index = 1;
        foreach ($rows as &$item) {
            if (empty($item['session_name'])) {
                $item['session_name'] = "السفاح الشمالي " . $index;
                $pdo->prepare("UPDATE numbers SET session_name = ? WHERE id = ?")->execute([$item['session_name'],$item['id']]);
            }
            if (empty($item['health_status'])) {$item['health_status'] = 'clean';
            }
            if (empty($item['telegram_name'])) {$item['telegram_name'] = '';
            }
            $index++;
        }
        echo json_encode($rows, JSON_UNESCAPED_UNICODE);
        break;

    case 'check_health':
        $phone = urldecode($_GET['phone'] ?? '');$cmd = "python tg_service.py check_health " . escapeshellarg($phone) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        $data = json_decode($clean, true);

        // حفظ حالة الفحص واسم الحساب مباشرة في قاعدة البيانات
        if ($data && isset($data['status'])) {
            $cleanP = preg_replace('/\D/', '',$phone);
            if (!empty($data['telegram_name'])) {
                $updateStmt =$pdo->prepare("UPDATE numbers SET health_status = ?, telegram_name = ? WHERE phone = ? OR phone LIKE ?");
                $updateStmt->execute([$data['status'],$data['telegram_name'], $phone, "%$cleanP%"]);
            } else {
                $updateStmt =$pdo->prepare("UPDATE numbers SET health_status = ? WHERE phone = ? OR phone LIKE ?");
                $updateStmt->execute([$data['status'], $phone, "%$cleanP%"]);
            }
        }

        echo $clean !== null ? $clean : json_encode(["status" => "unknown", "label" => "غير معروف", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'set_2fa':
        $phone = urldecode($_GET['phone'] ?? '');$password = urldecode($_GET['password'] ?? '');$hint = urldecode($_GET['hint'] ?? '');$cmd = "python tg_service.py set_2fa " . escapeshellarg($phone) . " " . escapeshellarg($password) . " " . escapeshellarg($hint) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        $res = json_decode($clean, true);

        // حفظ كلمة السر في قاعدة البيانات عند النجاح
        if ($res && isset($res['status']) &&$res['status'] === 'success') {
            $cleanP = preg_replace('/\D/', '',$phone);
            $stmt =$pdo->prepare("UPDATE numbers SET two_fa_password = ? WHERE phone = ? OR phone LIKE ?");
            $stmt->execute([$password, $phone, "%$cleanP%"]);
        }

        echo $clean !== null ? $clean : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'remove_2fa':
        $phone = urldecode($_GET['phone'] ?? '');$current_password = urldecode($_GET['current_password'] ?? '');$cmd = "python tg_service.py remove_2fa " . escapeshellarg($phone) . " " . escapeshellarg($current_password) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        $res = json_decode($clean, true);

        // تفريغ كلمة السر من قاعدة البيانات عند النجاح
        if ($res && isset($res['status']) &&$res['status'] === 'success') {
            $cleanP = preg_replace('/\D/', '',$phone);
            $stmt =$pdo->prepare("UPDATE numbers SET two_fa_password = '' WHERE phone = ? OR phone LIKE ?");
            $stmt->execute([$phone, "%$cleanP%"]);
        }

        echo $clean !== null ? $clean : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    // جلب كلمات سر الحسابات محمي بكلمة مرور المشرف الخاصة بك
    case 'get_2fa_passwords':
        $adminPass =$_GET['admin_pass'] ?? '';
        if ($adminPass !== 'aass12345') {
            echo json_encode(["status" => "error", "message" => "كلمة مرور الدخول غير صحيحة!"], JSON_UNESCAPED_UNICODE);
            exit;
        }

        $stmt =$pdo->query("SELECT phone, session_name, telegram_name, two_fa_password FROM numbers WHERE status = 'ready' ORDER BY id ASC");
        $list =$stmt->fetchAll();
        echo json_encode(["status" => "success", "data" => $list], JSON_UNESCAPED_UNICODE);
        break;

    // تحديث أو كتابة كلمة السر يدوياً لأي جلسة حالية
    case 'update_single_2fa_password':
        $adminPass =$_GET['admin_pass'] ?? '';
        if ($adminPass !== 'aass12345') {
            echo json_encode(["status" => "error", "message" => "غير مصرح لك بإجراء التعديل!"], JSON_UNESCAPED_UNICODE);
            exit;
        }
        $phone = urldecode($_GET['phone'] ?? '');
        $password = trim(urldecode($_GET['password'] ?? ''));
        $cleanP = preg_replace('/\D/', '',$phone);

        $stmt =$pdo->prepare("UPDATE numbers SET two_fa_password = ? WHERE phone = ? OR phone LIKE ?");
        $stmt->execute([$password, $phone, "%$cleanP%"]);
        echo json_encode(["status" => "success", "message" => "تم حفظ كلمة السر للحساب بنجاح!"], JSON_UNESCAPED_UNICODE);
        break;

    // الانضمام لقناة أو مجموعة تيليجرام
    case 'join_channel':
        $phone = urldecode($_GET['phone'] ?? '');$channel = urldecode($_GET['channel'] ?? '');$cmd = "python tg_service.py join_channel " . escapeshellarg($phone) . " " . escapeshellarg($channel) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        echo $clean !== null ? $clean : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'get_code':
        $phone = urldecode($_GET['phone'] ?? '');$cmd = "python tg_service.py get_code " . escapeshellarg($phone) . " 2>&1";
        $raw = shell_exec($cmd);
        $cleanJson = extract_clean_json($raw);
        $json = json_decode($cleanJson, true);
        echo $json !== null ? $cleanJson : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'check_login':
        $phone = urldecode($_GET['phone'] ?? '');$cmd = "python tg_service.py check_login " . escapeshellarg($phone) . " 2>&1";
        $raw = shell_exec($cmd);
        $cleanJson = extract_clean_json($raw);
        $json = json_decode($cleanJson, true);
        echo $json !== null ? $cleanJson : json_encode(["status" => "error", "logged_in" => false, "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'confirm_login':
        $phone = urldecode($_GET['phone'] ?? '');
        $cleanP = preg_replace('/\D/', '',$phone);
        $stmt =$pdo->prepare("UPDATE numbers SET logged_in_at = NOW(), expire_at = DATE_ADD(NOW(), INTERVAL 1 HOUR) WHERE phone = ? OR phone LIKE ?");
        $stmt->execute([$phone, "%$cleanP%"]);
        echo json_encode(["status" => "success", "message" => "تم تأكيد الدخول بنجاح! سيتم تسجيل الخروج تلقائياً بعد ساعة"], JSON_UNESCAPED_UNICODE);
        break;

    case 'reset_login':
        $phone = urldecode($_GET['phone'] ?? '');
        $cleanP = preg_replace('/\D/', '',$phone);

        $cmd = "python tg_service.py terminate_others " . escapeshellarg($phone) . " 2>&1";
        $raw = shell_exec($cmd);

        $stmt =$pdo->prepare("UPDATE numbers SET logged_in_at = NULL, expire_at = NULL, status = 'ready' WHERE phone = ? OR phone LIKE ?");
        $stmt->execute([$phone, "%$cleanP%"]);

        echo json_encode(["status" => "success", "message" => "تم إلغاء السحب وإعادة الرقم متاحاً للمخزون بنجاح!"], JSON_UNESCAPED_UNICODE);
        break;

    case 'logout':
        $phone = urldecode($_GET['phone'] ?? '');
        $cleanP = preg_replace('/\D/', '',$phone);

        $cmd = "python tg_service.py logout " . escapeshellarg($phone) . " 2>&1";
        shell_exec($cmd);

        $stmt =$pdo->prepare("DELETE FROM numbers WHERE phone = ? OR phone LIKE ?");
        $stmt->execute([$phone, "%$cleanP%"]);

        echo json_encode(["status" => "success", "message" => "تم تسجيل الخروج وحذف الجلسة بنجاح"], JSON_UNESCAPED_UNICODE);
        break;

    case 'upload_temp_photo':
        if (!isset($_FILES['photo'])) {
            echo json_encode(["status" => "error", "message" => "لم يتم استلام أي صورة"]);
            exit;
        }
        $targetDir = __DIR__ . "/uploads/";
        if (!file_exists($targetDir)) mkdir($targetDir, 0777, true);
        $fileName = time() . "_" . basename($_FILES["photo"]["name"]);
        $targetFilePath = $targetDir .$fileName;
        if (move_uploaded_file($_FILES["photo"]["tmp_name"], $targetFilePath)) {
            echo json_encode(["status" => "success", "file_path" => $targetFilePath]);
        } else {
            echo json_encode(["status" => "error", "message" => "فشل حفظ الصورة على السيرفر"]);
        }
        break;

    case 'change_name':
        $phone = urldecode($_GET['phone'] ?? '');$first = urldecode($_GET['first_name'] ?? '');$last  = urldecode($_GET['last_name'] ?? '');$cmd = "python tg_service.py change_name " . escapeshellarg($phone) . " " . escapeshellarg($first) . " " . escapeshellarg($last) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        $res = json_decode($clean, true);

        // حفظ الاسم في قاعدة البيانات فور نجاح التغيير
        if ($res && isset($res['status']) && $res['status'] === 'success') {$fullName = trim($first . ' ' .$last);
            $cleanP = preg_replace('/\D/', '',$phone);
            $updateStmt =$pdo->prepare("UPDATE numbers SET telegram_name = ? WHERE phone = ? OR phone LIKE ?");
            $updateStmt->execute([$fullName, $phone, "%$cleanP%"]);
        }

        echo $clean !== null ? $clean : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'change_photo':
        $phone = urldecode($_GET['phone'] ?? '');$photo = urldecode($_GET['photo_path'] ?? '');$cmd = "python tg_service.py change_photo " . escapeshellarg($phone) . " " . escapeshellarg($photo) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        echo $clean !== null ? $clean : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    case 'bot_referral':
        $phone = urldecode($_GET['phone'] ?? '');$link  = urldecode($_GET['link'] ?? '');$cmd = "python tg_service.py bot_referral " . escapeshellarg($phone) . " " . escapeshellarg($link) . " 2>&1";
        $raw = shell_exec($cmd);
        $clean = extract_clean_json($raw);
        echo $clean !== null ? $clean : json_encode(["status" => "error", "message" => trim($raw)], JSON_UNESCAPED_UNICODE);
        break;

    default:
        echo json_encode(["error" => "أمر غير معروف"], JSON_UNESCAPED_UNICODE);
        break;
}
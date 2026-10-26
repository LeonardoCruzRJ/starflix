package com.starflix.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import java.util.concurrent.Executors

/** 58.11: leitor de QR (CameraX + ZXing core). A permissão da câmera é pedida só aqui; devolve o texto lido em [EXTRA_TEXT]. */
class QrScanActivity : AppCompatActivity() {
    private lateinit var preview: PreviewView
    private val exec = Executors.newSingleThreadExecutor()
    @Volatile private var done = false

    private val perm = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) startCamera() else {
            Toast.makeText(this, R.string.camera_denied, Toast.LENGTH_LONG).show()
            finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val d = resources.displayMetrics.density
        preview = PreviewView(this)
        val hint = TextView(this).apply {
            text = getString(R.string.scan_hint)
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.parseColor("#99000000"))
            gravity = Gravity.CENTER
            setPadding((16 * d).toInt(), (16 * d).toInt(), (16 * d).toInt(), (16 * d).toInt())
        }
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            addView(preview, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            addView(hint, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.TOP))
        }
        setContentView(root)
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) startCamera()
        else perm.launch(Manifest.permission.CAMERA)
    }

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            val provider = future.get()
            val pv = Preview.Builder().build().also { it.setSurfaceProvider(preview.surfaceProvider) }
            val an = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
            val reader = MultiFormatReader().apply {
                setHints(mapOf<DecodeHintType, Any>(DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE)))
            }
            an.setAnalyzer(exec) { img ->
                try {
                    if (!done) {
                        val p = img.planes[0]
                        val buf = p.buffer
                        val bytes = ByteArray(buf.remaining())
                        buf.get(bytes)
                        val src = PlanarYUVLuminanceSource(bytes, p.rowStride, img.height, 0, 0, img.width, img.height, false)
                        val text = reader.decodeWithState(BinaryBitmap(HybridBinarizer(src))).text
                        done = true
                        runOnUiThread {
                            setResult(RESULT_OK, Intent().putExtra(EXTRA_TEXT, text))
                            finish()
                        }
                    }
                } catch (e: Exception) {
                    // nenhum QR neste quadro
                } finally {
                    reader.reset()
                    img.close()
                }
            }
            try {
                provider.unbindAll()
                provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, pv, an)
            } catch (e: Exception) {
                finish()
            }
        }, ContextCompat.getMainExecutor(this))
    }

    override fun onDestroy() {
        exec.shutdown()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_TEXT = "text"
    }
}

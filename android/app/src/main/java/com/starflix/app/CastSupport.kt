package com.starflix.app

import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import com.google.android.gms.cast.framework.CastContext
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability

/** 67.2: acesso ao Cast só no celular. Na TV, sem Google Play Services ou se o framework falhar, devolve null (sem botão, o app segue normal). */
object CastSupport {
    private var ctx: CastContext? = null
    private var tried = false

    fun context(c: Context): CastContext? {
        if (tried) return ctx
        tried = true
        ctx = try {
            val ui = c.getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
            val isTv = ui?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
            if (isTv || GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(c) != ConnectionResult.SUCCESS) null
            else CastContext.getSharedInstance(c.applicationContext)
        } catch (_: Throwable) {
            null
        }
        return ctx
    }

    fun available(c: Context) = context(c) != null
}

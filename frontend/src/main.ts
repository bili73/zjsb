import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'dayjs/locale/zh-cn.js'
import 'element-plus/dist/index.css'
import { installGlobalDiagnostics, installVueDiagnostics } from './diagnostics.ts'
import App from './App.vue'
import './style.css'

installGlobalDiagnostics()
const app = createApp(App)
app.use(ElementPlus, { locale: zhCn })
installVueDiagnostics(app)
app.mount('#app')

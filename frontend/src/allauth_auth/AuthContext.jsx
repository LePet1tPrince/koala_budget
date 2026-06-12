import { useEffect, createContext, useState } from 'react'
import { getAuth, getConfig } from '../lib/allauth'
import LoadingScreen from 'assets/javascript/utilities/Loading'
import LoadError from 'assets/javascript/utilities/LoadError'

export const AuthContext = createContext(null)


export function AuthContextProvider (props) {
  const [auth, setAuth] = useState(undefined)
  const [config, setConfig] = useState(undefined)

  useEffect(() => {
    function onAuthChanged (e) {
      setAuth(auth => {
        if (typeof auth === 'undefined') {
          console.log('Authentication status loaded')
        } else {
          console.log('Authentication status updated')
        }
        return e.detail
      }
      )
    }

    document.addEventListener('allauth.auth.change', onAuthChanged)
    getAuth().then(data => setAuth(data)).catch((e) => {
      console.error(e)
      setAuth(false)
    })
    getConfig().then(data => setConfig(data)).catch((e) => {
      console.error(e);
      // Surface the failure instead of spinning forever on the loading screen
      setConfig(false)
    })
    return () => {
      document.removeEventListener('allauth.auth.change', onAuthChanged)
    }
  }, [])
  const failed = auth === false || config === false
  const loading = !failed && ((typeof auth === 'undefined') || config?.status !== 200)
  return (
    <AuthContext.Provider value={{ auth, config }}>
      {loading
        ? <LoadingScreen />
        : (failed
            ? <LoadError />
            : props.children)}
    </AuthContext.Provider>
  )
}

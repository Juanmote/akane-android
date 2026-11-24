using UnityEngine;
using UnityEngine.SceneManagement;

// AKANE (APK genérica): escena de arranque vacía, lo único que va dentro de la APK.
// Carga la primera escena real del juego, que está en la OBB generada con la copia del usuario.
public class AkaneBoot : MonoBehaviour
{
	private void Start()
	{
		SceneManager.LoadScene(1);
	}
}

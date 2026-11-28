from datetime import timedelta


def recovery_message(*, name: str, link: str, valid_for: timedelta) -> tuple[str, str]:
    first_name = name.split()[0]
    minutes = int(valid_for.total_seconds() // 60)
    body = (
        f"Olá, {first_name}!\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta no Organizaê.\n\n"
        f"Para criar uma nova senha, acesse o link abaixo. Ele vale por {minutes} "
        "minutos e só pode ser usado uma vez:\n\n"
        f"{link}\n\n"
        "Se você não fez esse pedido, ignore este e-mail: sua senha continua a mesma.\n"
    )
    return "Recuperação de senha - Organizaê", body
